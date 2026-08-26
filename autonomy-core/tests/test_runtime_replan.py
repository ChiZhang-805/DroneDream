from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from dronedream_agent_core.contracts import (
    CatalogEntity,
    MapAsset,
    MapCatalog,
    MapEdge,
    MapNode,
    ModelCallRecord,
    Px4CoordinateContract,
    Px4Track,
    Px4TrackPoint,
    RuntimeControlSession,
    RuntimeHoldAcknowledgement,
    RuntimeInterruptionDecision,
    RuntimeMessageClassification,
    RuntimeUserMessage,
    Vector3,
    VehicleAsset,
    WorldTrackPoint,
)
from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.runtime_interrupt import _runtime_adoption_gates
from dronedream_agent_core.runtime_replan import (
    build_runtime_coverage_replacement,
    build_runtime_replacement,
    build_runtime_speed_replacement,
)


def test_runtime_destination_change_builds_bound_clear_replacement(tmp_path) -> None:
    now = datetime.now(UTC)
    graph = MapAsset(
        asset_id="map-a",
        name="map",
        nodes=[
            MapNode(
                node_id="office",
                label="Office",
                position_m=Vector3(x=0, y=0, z=1),
                semantic="office",
            ),
            MapNode(
                node_id="guard-house",
                label="Guard house",
                position_m=Vector3(x=5, y=0, z=1),
                semantic="pickup",
            ),
        ],
        edges=[
            MapEdge(
                edge_id="office-guard",
                from_node="office",
                to_node="guard-house",
                distance_m=5,
                minimum_clearance_m=2,
                speed_limit_mps=1,
                qualification="flight-verified",
                evidence_sha256="1" * 64,
            )
        ],
        named_entities={"office": "office", "guard-house": "guard-house"},
    )
    semantic = tmp_path / "semantic.json"
    semantic.write_text(
        json.dumps(
            {
                "collision_primitives": [
                    {
                        "name": "far-wall",
                        "center_x": 100,
                        "center_y": 100,
                        "center_z": 1,
                        "size_x": 1,
                        "size_y": 1,
                        "size_z": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog = MapCatalog(
        scene_id="scene-a",
        semantic_sha256="2" * 64,
        entities=[
            CatalogEntity(
                entity_id="guard-house",
                aliases=["guard-house", "保安亭"],
                position_m=Vector3(x=5, y=0, z=1),
                semantic="pickup",
                source_pointer="/guard-house",
            )
        ],
        topology_available=True,
    )
    vehicle = VehicleAsset(
        asset_id="vehicle-a",
        name="vehicle",
        dry_mass_kg=1,
        max_takeoff_mass_kg=2,
        body_radius_m=0.2,
        body_height_m=0.2,
        max_speed_mps=2,
        max_acceleration_mps2=2,
        qualified_range_m=1000,
        reserve_battery_percent=20,
        max_pickup_payload_kg=0.5,
        sensors=["camera"],
    )
    prior_track = Px4Track(
        coordinate_contract=Px4CoordinateContract(
            model_root_world_enu_m=[0, 0, 0],
            collision_center_above_model_root_m=0.2,
        ),
        points=[
            Px4TrackPoint(x=0, y=0, z=0.8, phase="launch", speed_limit_mps=1),
            Px4TrackPoint(x=0, y=5, z=0.8, phase="land", speed_limit_mps=1),
        ],
        source_world_points=[
            WorldTrackPoint(east_m=0, north_m=0, up_m=1),
            WorldTrackPoint(east_m=5, north_m=0, up_m=1),
        ],
        waypoint_hold_seconds=0.2,
    )
    message = RuntimeUserMessage(
        message_id="runtime-msg-" + "a" * 32,
        conversation_id="conversation-a",
        mission_id="mission-" + "b" * 32,
        plan_revision_id="plan-" + "c" * 32,
        contract_id="mission-contract-a",
        execution_id="execution-" + "d" * 32,
        text="改去保安亭取外卖，再返回办公室",
        submitted_at=now,
    )
    acknowledgement = RuntimeHoldAcknowledgement(
        message_sha256=sha256_json(message),
        message_id=message.message_id,
        execution_id=message.execution_id,
        interrupted_phase="TRACK",
        schedule_index=10,
        detected_at=now,
        detection_latency_ms=20,
        stable_at=now,
        stabilization_latency_ms=900,
        frozen_command_ned_m=Vector3(x=0, y=0, z=-0.8),
        hold_command_ned_m=Vector3(x=0, y=0, z=-0.8),
        observed_position_ned_m=Vector3(x=0, y=0, z=-0.8),
        observed_velocity_ned_mps=Vector3(x=0, y=0, z=0),
        position_error_m=0,
        speed_mps=0,
        deterministic_gates={"stable": True},
    )
    classification = RuntimeMessageClassification(
        message_kind="mission_amendment",
        requested_action="replan",
        target_entity="校园门口的保安亭",
        requires_plan_revision=True,
        summary="Change pickup destination to the guard house.",
    )
    decision = RuntimeInterruptionDecision(
        message_sha256=sha256_json(message),
        hold_ack_sha256=sha256_json(acknowledgement),
        classification=classification,
        model_call=ModelCallRecord(
            call_id="model-" + "e" * 24,
            role="runtime_message_classifier",
            attempt=1,
            input_sha256="3" * 64,
            output_sha256=sha256_json(classification),
            output_schema="RuntimeMessageClassification",
            provider="openai",
            model="gpt-test",
            latency_ms=10,
            created_at=now,
        ),
        authorized_action="hold_for_replan",
        authorization_gates={"stable": True},
        decision_reason="Destination changed.",
    )
    semantic_sha256 = hashlib.sha256(semantic.read_bytes()).hexdigest()

    replacement = build_runtime_replacement(
        message=message,
        acknowledgement=acknowledgement,
        decision=decision,
        replacement_sequence=1,
        prior_track_sha256=sha256_json(prior_track),
        prior_track=prior_track,
        graph=graph,
        catalog=catalog,
        semantic_path=semantic,
        vehicle=vehicle,
        expected_map_sha256=sha256_json(graph),
        expected_semantic_sha256=semantic_sha256,
        expected_vehicle_asset_id=vehicle.asset_id,
        return_node="office",
    )

    assert replacement.target_node == "guard-house"
    assert replacement.route.node_ids == [
        "runtime-current",
        "office",
        "guard-house",
        "office",
    ]
    assert replacement.clearance.accepted

    return_message = message.model_copy(
        update={
            "message_id": "runtime-msg-" + "f" * 32,
            "text": "返航点改成办公室，但先继续当前取件任务",
        }
    )
    return_acknowledgement = acknowledgement.model_copy(
        update={
            "message_id": return_message.message_id,
            "message_sha256": sha256_json(return_message),
        }
    )
    return_classification = classification.model_copy(
        update={
            "requested_action": "set_return_point",
            "target_entity": "office",
            "summary": "Keep the objective and change only the return point.",
        }
    )
    return_decision = decision.model_copy(
        update={
            "message_sha256": sha256_json(return_message),
            "hold_ack_sha256": sha256_json(return_acknowledgement),
            "classification": return_classification,
        }
    )
    changed_return = build_runtime_replacement(
        message=return_message,
        acknowledgement=return_acknowledgement,
        decision=return_decision,
        replacement_sequence=2,
        prior_track_sha256=sha256_json(prior_track),
        prior_track=prior_track,
        graph=graph,
        catalog=catalog,
        semantic_path=semantic,
        vehicle=vehicle,
        expected_map_sha256=sha256_json(graph),
        expected_semantic_sha256=semantic_sha256,
        expected_vehicle_asset_id=vehicle.asset_id,
        return_node="office",
        active_target_node="guard-house",
    )

    assert changed_return.target_node == "guard-house"
    assert changed_return.return_node == "office"
    assert changed_return.amendment_parameters["new_return_node"] == "office"
    assert "guard-house" in changed_return.route.node_ids
    assert replacement.track.points[0].x == 0
    assert replacement.track.points[0].y == 0
    assert replacement.track.points[-1].phase == "land"
    assert all(replacement.deterministic_gates.values())

    session = RuntimeControlSession(
        conversation_id=message.conversation_id,
        mission_id=message.mission_id,
        plan_revision_id=message.plan_revision_id,
        contract_id=message.contract_id,
        execution_id=message.execution_id,
        prepared_mission_sha256="f" * 64,
        created_at=now,
    )
    adoption = {
        "message_id": message.message_id,
        "execution_id": message.execution_id,
        "replacement_sequence": replacement.replacement_sequence,
        "replacement_sha256": sha256_json(replacement),
        "track_sha256": sha256_json(replacement.track),
    }
    assert all(
        _runtime_adoption_gates(
            adoption=adoption,
            replacement=replacement,
            session=session,
        ).values()
    )
    adoption["track_sha256"] = "0" * 64
    assert not _runtime_adoption_gates(
        adoption=adoption,
        replacement=replacement,
        session=session,
    )["track_hash"]

    speed_message = message.model_copy(
        update={
            "message_id": "runtime-msg-" + "9" * 32,
            "text": "后续速度调整为每秒 0.3 米",
        }
    )
    speed_ack = acknowledgement.model_copy(
        update={
            "message_id": speed_message.message_id,
            "message_sha256": sha256_json(speed_message),
        }
    )
    speed_classification = RuntimeMessageClassification(
        message_kind="motion_adjustment",
        requested_action="set_speed",
        requires_plan_revision=True,
        summary="Cap the remaining trajectory speed.",
        parameters={"maximum_speed_mps": 0.3},
    )
    speed_decision = decision.model_copy(
        update={
            "message_sha256": sha256_json(speed_message),
            "hold_ack_sha256": sha256_json(speed_ack),
            "classification": speed_classification,
        }
    )

    speed_replacement = build_runtime_speed_replacement(
        message=speed_message,
        acknowledgement=speed_ack,
        decision=speed_decision,
        replacement_sequence=2,
        prior_track_sha256=sha256_json(replacement.track),
        prior_track=replacement.track,
        graph=graph,
        semantic_path=semantic,
        vehicle=vehicle,
        expected_map_sha256=sha256_json(graph),
        expected_semantic_sha256=semantic_sha256,
        expected_vehicle_asset_id=vehicle.asset_id,
    )

    assert speed_replacement.amendment_action == "set_speed"
    assert speed_replacement.amendment_parameters == {"maximum_speed_mps": 0.3}
    assert all(point.speed_limit_mps <= 0.3 for point in speed_replacement.track.points)
    assert speed_replacement.track.points[0].x == speed_ack.observed_position_ned_m.x
    assert speed_replacement.track.points[0].y == speed_ack.observed_position_ned_m.y
    assert all(speed_replacement.deterministic_gates.values())

    coverage_message = message.model_copy(
        update={
            "message_id": "runtime-msg-" + "8" * 32,
            "text": "把保安亭周围两米见方的区域往复覆盖一遍",
        }
    )
    coverage_ack = acknowledgement.model_copy(
        update={
            "message_id": coverage_message.message_id,
            "message_sha256": sha256_json(coverage_message),
        }
    )
    coverage_classification = RuntimeMessageClassification(
        message_kind="mission_amendment",
        requested_action="set_coverage",
        target_entity="guard-house",
        requires_plan_revision=True,
        summary="Cover the guard-house area.",
        parameters={
            "width_m": 2.0,
            "height_m": 2.0,
            "lane_spacing_m": 0.5,
            "boundary_margin_m": 0.2,
            "altitude_m": 1.0,
        },
    )
    coverage_decision = decision.model_copy(
        update={
            "message_sha256": sha256_json(coverage_message),
            "hold_ack_sha256": sha256_json(coverage_ack),
            "classification": coverage_classification,
        }
    )
    coverage = build_runtime_coverage_replacement(
        message=coverage_message,
        acknowledgement=coverage_ack,
        decision=coverage_decision,
        replacement_sequence=3,
        prior_track_sha256=sha256_json(speed_replacement.track),
        prior_track=speed_replacement.track,
        graph=graph,
        catalog=catalog,
        semantic_path=semantic,
        vehicle=vehicle,
        expected_map_sha256=sha256_json(graph),
        expected_semantic_sha256=semantic_sha256,
        expected_vehicle_asset_id=vehicle.asset_id,
        return_node="office",
    )

    assert coverage.amendment_action == "set_coverage"
    assert coverage.amendment_parameters["pattern"] == "lawnmower"
    assert coverage.amendment_parameters["lane_count"] >= 2
    assert (
        len([node for node in coverage.route.node_ids if node.startswith("runtime-coverage-")]) >= 4
    )
    assert coverage.route.goal_node == "office"
    assert all(coverage.deterministic_gates.values())
