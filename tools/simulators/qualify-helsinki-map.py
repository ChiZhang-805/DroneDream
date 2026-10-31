#!/usr/bin/env python3
"""Fly one generated Helsinki map with real PX4 SITL and Gazebo Harmonic."""

from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import school_map_px4_mission as support

from app.autonomy.px4_standard_vtol_vehicle import export_standard_vtol_gazebo_artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-root", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--px4-root", type=Path, default=Path("/opt/PX4-Autopilot"))
    parser.add_argument("--vehicle-package", type=Path)
    parser.add_argument(
        "--vehicle-model", choices=("x500-depth", "standard-vtol"), default="x500-depth"
    )
    parser.add_argument("--velocity-m-s", type=float, default=5.0)
    parser.add_argument("--cruise-altitude-m", type=float, default=8.0)
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def shortest_path(graph: dict[str, Any], start: str, goal: str) -> list[str]:
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for edge in graph["edges"]:
        left, right = edge["from_node"], edge["to_node"]
        distance = float(edge["distance_m"])
        adjacency.setdefault(left, []).append((right, distance))
        if edge.get("bidirectional", False):
            adjacency.setdefault(right, []).append((left, distance))
    distance_by_node = {start: 0.0}
    parent: dict[str, str] = {}
    queue: list[tuple[float, str]] = [(0.0, start)]
    while queue:
        distance, current = heapq.heappop(queue)
        if current == goal:
            break
        if distance != distance_by_node.get(current):
            continue
        for candidate, edge_distance in adjacency.get(current, []):
            next_distance = distance + edge_distance
            if next_distance >= distance_by_node.get(candidate, math.inf):
                continue
            distance_by_node[candidate] = next_distance
            parent[candidate] = current
            heapq.heappush(queue, (next_distance, candidate))
    if goal not in distance_by_node:
        raise ValueError("launch and outdoor handoff are not connected")
    path = [goal]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path


def vehicle_contract(package: Path) -> dict[str, Any]:
    with zipfile.ZipFile(package) as bundle:
        value = json.loads(bundle.read("normalized/vehicle/vehicle.json"))
    if value.get("asset_id") != "dronedream.my-drone.v1":
        raise ValueError("qualification requires the bundled My Drone vehicle contract")
    return value


def grounded_model_root(
    semantic: dict[str, Any], vehicle: dict[str, Any]
) -> tuple[float, float, float]:
    spawn = semantic["runtime_bindings"]["vehicle_spawn"]
    support_tops: list[float] = []
    for primitive in semantic["collision_primitives"]:
        if primitive.get("semantic") not in {"terrain", "road", "pavement", "launch-pad"}:
            continue
        if not all(
            key in primitive
            for key in ("center_x", "center_y", "center_z", "size_x", "size_y", "size_z")
        ):
            continue
        if (
            abs(float(spawn["x"]) - float(primitive["center_x"])) <= float(primitive["size_x"]) / 2
            and abs(float(spawn["y"]) - float(primitive["center_y"]))
            <= float(primitive["size_y"]) / 2
        ):
            support_tops.append(float(primitive["center_z"]) + float(primitive["size_z"]) / 2)
    if not support_tops:
        raise ValueError("launch point has no load-bearing support surface")
    offset = vehicle["collision_center_offset_model_m"]
    support_z = min(support_tops, key=lambda value: abs(value - float(spawn["z"])))
    return (
        float(spawn["x"]) - float(offset["x"]),
        float(spawn["y"]) - float(offset["y"]),
        support_z
        - float(
            vehicle.get(
                "model_root_to_contact_m", float(offset["z"]) - float(vehicle["body_height_m"]) / 2
            )
        ),
    )


def route_contract(
    map_root: Path,
    altitude_m: float,
    velocity_m_s: float,
    vehicle: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], tuple[float, float, float], list[dict[str, Any]]]:
    graph = json.loads((map_root / "navigation-graph.json").read_text(encoding="utf-8"))
    semantic = json.loads((map_root / "gazebo" / "semantic.json").read_text(encoding="utf-8"))
    start_id = graph["named_entities"]["launch"]
    goal_id = graph["named_entities"]["outdoor_handoff"]
    nodes = {entry["node_id"]: entry for entry in graph["nodes"]}
    from dronedream_agent_core.contracts import MapAsset, RouteQuery, Vector3
    from dronedream_agent_core.known_map_planner import KnownMapMetricPlanner, MetricPlannerPolicy

    planner = KnownMapMetricPlanner(
        graph=MapAsset.model_validate(graph),
        semantic_path=map_root / "gazebo" / "semantic.json",
        vehicle_diameter_m=vehicle["body_radius_m"] * 2,
        vehicle_height_m=vehicle["body_height_m"],
        policy=MetricPlannerPolicy(required_clearance_m=0.8),
    )
    outward = planner.plan_positions(
        RouteQuery(start_node=start_id, goal_node=goal_id),
        start_position_m=Vector3(**{**nodes[start_id]["position_m"], "z": altitude_m}),
        goal_position_m=Vector3(**{**nodes[goal_id]["position_m"], "z": altitude_m}),
    )
    outward_ids = outward.node_ids
    root = grounded_model_root(semantic, vehicle)
    offset_value = vehicle["collision_center_offset_model_m"]
    offset = (float(offset_value["x"]), float(offset_value["y"]), float(offset_value["z"]))
    round_trip_ids = [*outward_ids, *reversed(outward_ids[:-1])]
    world_points = [
        {
            "east_m": point.x,
            "north_m": point.y,
            "up_m": point.z,
        }
        for point in [*outward.positions_m, *reversed(outward.positions_m[:-1])]
    ]
    points = []
    for index, world in enumerate(world_points):
        phase = (
            "launch"
            if index == 0
            else "land"
            if index == len(world_points) - 1
            else "pickup"
            if index == len(outward_ids) - 1
            else "return"
            if index >= len(outward_ids)
            else "transit"
        )
        points.append(
            {
                "x": world["north_m"] - root[1] - offset[1],
                "y": world["east_m"] - root[0] - offset[0],
                "z": world["up_m"] - root[2] - offset[2],
                "phase": phase,
                "speed_limit_mps": velocity_m_s,
            }
        )
    edge_ids = [*outward.edge_ids, *reversed(outward.edge_ids)]
    positions = [
        {"x": world["east_m"], "y": world["north_m"], "z": world["up_m"]} for world in world_points
    ]
    route = {
        "schema_version": "dronedream.graph-route.v1",
        "start_node": start_id,
        "goal_node": start_id,
        "node_ids": round_trip_ids,
        "edge_ids": edge_ids,
        "positions_m": positions,
        "route_length_m": sum(
            math.dist(
                (left["x"], left["y"], left["z"]),
                (right["x"], right["y"], right["z"]),
            )
            for left, right in zip(positions, positions[1:], strict=False)
        ),
        "all_edges_flight_verified": False,
    }
    track = {
        "schema_version": "dronedream.px4-track.v2",
        "track_type": "custom",
        "stop_at_waypoints": True,
        "waypoint_hold_seconds": 0.35,
        "waypoint_position_tolerance_m": 0.35,
        "waypoint_speed_tolerance_mps": 0.25,
        "waypoint_stable_window_seconds": 0.5,
        "waypoint_settle_timeout_seconds": 20.0,
        "coordinate_contract": {
            "source": "Gazebo ENU vehicle-collision-envelope center",
            "executor_x": "PX4 local north physically mapped to qualified-map ENU north",
            "executor_y": "PX4 local east physically mapped to qualified-map ENU east",
            "executor_z": "PX4 local up",
            "model_root_world_enu_m": list(root),
            "collision_center_offset_model_m": list(offset),
        },
        "points": points,
        "source_world_points": world_points,
    }
    return route, track, root, track["points"]


def collision_count(
    samples: list[support.GazeboPoseSample], semantic: dict[str, Any], vehicle: dict[str, Any]
) -> int:
    collisions = 0
    for sample in samples:
        for primitive in semantic["collision_primitives"]:
            if primitive.get("semantic") in {"terrain", "road", "pavement", "launch-pad"}:
                continue
            dx = sample.model_root_x - float(primitive["center_x"])
            dy = sample.model_root_y - float(primitive["center_y"])
            yaw = -float(primitive.get("yaw_rad", 0.0))
            local_x = dx * math.cos(yaw) - dy * math.sin(yaw)
            local_y = dx * math.sin(yaw) + dy * math.cos(yaw)
            horizontal = (
                abs(local_x) <= float(primitive["size_x"]) / 2 + vehicle["body_radius_m"]
                and abs(local_y) <= float(primitive["size_y"]) / 2 + vehicle["body_radius_m"]
            )
            vertical = (
                abs(
                    sample.model_root_z
                    + vehicle["collision_center_offset_model_m"]["z"]
                    - float(primitive["center_z"])
                )
                <= (float(primitive["size_z"]) + vehicle["body_height_m"]) / 2
            )
            if horizontal and vertical:
                collisions += 1
                break
    return collisions


def main() -> int:
    args = parse_args()
    map_root = args.map_root.resolve()
    run_dir = args.run_dir.resolve()
    px4_root = args.px4_root.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    semantic = json.loads((map_root / "gazebo" / "semantic.json").read_text(encoding="utf-8"))
    if args.vehicle_model == "standard-vtol":
        # Geometry envelope includes the full wing, camera and attached parcel.
        # These dimensions are candidate inputs, not measured flight capability.
        vehicle = {
            "body_radius_m": 1.2,
            "body_height_m": 0.5,
            "collision_center_offset_model_m": {"x": 0.0, "y": 0.0, "z": 0.3},
            "model_root_to_contact_m": 0.151,
        }
        autopilot_model, autostart = "standard_vtol", "4004"
    else:
        if args.vehicle_package is None:
            raise ValueError("X500 qualification needs --vehicle-package")
        vehicle = vehicle_contract(args.vehicle_package.resolve())
        autopilot_model, autostart = "x500", "4001"
    route, track, spawn, points = route_contract(
        map_root, args.cruise_altitude_m, args.velocity_m_s, vehicle
    )
    from dronedream_agent_core.collision import validate_route_clearance
    from dronedream_agent_core.contracts import GraphRoute

    clearance = validate_route_clearance(
        GraphRoute.model_validate(route),
        map_root / "gazebo" / "semantic.json",
        vehicle_diameter_m=vehicle["body_radius_m"] * 2,
        vehicle_height_m=vehicle["body_height_m"],
        sample_interval_m=0.05,
    )
    write_json(run_dir / "clearance.json", clearance.model_dump(mode="json"))
    if not clearance.accepted or clearance.minimum_clearance_m < 0.79:
        raise ValueError("route does not fit the selected aircraft envelope")
    write_json(run_dir / "mission-route.json", route)
    track_path = run_dir / "reference_track.json"
    params_path = run_dir / "controller_params.json"
    write_json(track_path, track)
    write_json(
        params_path,
        {
            "kp_xy": 1.0,
            "kd_xy": 0.2,
            "ki_xy": 0.05,
            "vel_limit": args.velocity_m_s,
            "accel_limit": 0.8,
            "disturbance_rejection": 0.5,
        },
    )
    write_json(
        run_dir / "qualification-inputs.json",
        {
            "schema_version": "dronedream.map-flight-qualification.v1",
            "natural_language_acceptance": False,
            "en-US": (
                f"Take off in {semantic['display_name']['en-US']}, follow the "
                "mapped outdoor route to the handoff point, return home, and land."
            ),
            "zh-CN": (
                f"在{semantic['display_name']['zh-CN']}起飞，沿地图中的室外路径"
                "飞到交接点，然后返航并降落。"
            ),
            "resolved_entities": ["launch", "outdoor_handoff"],
            "route_source": "City of Helsinki Liikennevaylat",
        },
    )

    support.WORLD_NAME = f"{semantic['scene_id']}-world"
    support.DEFAULT_POSE_TOPIC = f"/world/{support.WORLD_NAME}/dynamic_pose/info"
    support.VEHICLE_ENTITY = "my_drone"
    gz_binary = support._require_executable("gz")
    trial_rootfs, px4_executable = support._prepare_isolated_px4_rootfs(px4_root, run_dir)
    vehicle_dir = run_dir / "my-drone"
    if args.vehicle_model == "standard-vtol":
        export_standard_vtol_gazebo_artifact(vehicle_dir)
    else:
        support.export_my_drone_gazebo_artifact(vehicle_dir)
    partition = f"dronedream_{semantic['scene_id'].replace('-', '_')}_{os.getpid()}"
    env = os.environ.copy()
    px4_plugins = px4_root / "build/px4_sitl_default/src/modules/simulation/gz_plugins"
    server_config = px4_root / "src/modules/simulation/gz_bridge/server.config"
    state_root = run_dir / "runtime-state"
    for name in ("cache", "config", "data"):
        (state_root / name).mkdir(parents=True, exist_ok=True)
    resource_paths = [
        str(map_root / "gazebo"),
        str(vehicle_dir.parent),
        str(px4_root / "Tools/simulation/gz/models"),
    ]
    if env.get("GZ_SIM_RESOURCE_PATH"):
        resource_paths.append(env["GZ_SIM_RESOURCE_PATH"])
    env.update(
        {
            "GZ_PARTITION": partition,
            "GZ_SIM_RESOURCE_PATH": ":".join(resource_paths),
            "GZ_SIM_SYSTEM_PLUGIN_PATH": ":".join(
                filter(None, (str(px4_plugins), env.get("GZ_SIM_SYSTEM_PLUGIN_PATH")))
            ),
            "GZ_SIM_SERVER_CONFIG_PATH": str(server_config),
            "HEADLESS": "1",
            "PX4_GZ_STANDALONE": "1",
            "PX4_GZ_MODEL_NAME": "my_drone",
            "PX4_SYS_AUTOSTART": autostart,
            "GZ_IP": "127.0.0.1",
            "PYTHONUNBUFFERED": "1",
            "XDG_CACHE_HOME": str(state_root / "cache"),
            "XDG_CONFIG_HOME": str(state_root / "config"),
            "XDG_DATA_HOME": str(state_root / "data"),
        }
    )
    gazebo = px4 = executor = None
    recorder = None
    with (
        (run_dir / "gazebo.log").open("w", encoding="utf-8") as gazebo_log,
        (run_dir / "px4.log").open("w", encoding="utf-8") as px4_log,
        (run_dir / "executor.stdout.log").open("w", encoding="utf-8") as executor_stdout,
        (run_dir / "executor.stderr.log").open("w", encoding="utf-8") as executor_stderr,
        (run_dir / "pose.stderr.log").open("w", encoding="utf-8") as pose_stderr,
    ):
        try:
            gazebo = subprocess.Popen(
                [gz_binary, "sim", "-r", "-s", str(map_root / "gazebo" / "world.physics.sdf")],
                env=env,
                stdout=gazebo_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            support._wait_for_world(gz_binary, env, 90)
            spawn_receipt = support._create_gazebo_entity(
                gz_binary,
                env,
                sdf_filename=vehicle_dir / "model.sdf",
                entity_name="my_drone",
                world_pose=spawn,
            )
            write_json(run_dir / "vehicle_spawn.json", spawn_receipt)
            recorder = support.GazeboPoseRecorder(
                gz_binary, env, run_dir / "gazebo_pose_samples.csv", pose_stderr
            )
            recorder.start()
            px4 = subprocess.Popen(
                [str(px4_executable), "-d", "-w", str(trial_rootfs), str(trial_rootfs)],
                cwd=trial_rootfs,
                env=env,
                stdout=px4_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            support._wait_for_vehicle(gz_binary, env, 120)
            executor_path = Path(__file__).with_name("px4_offboard_track_executor.py")
            route_distance = sum(
                math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
                for a, b in zip(points, points[1:], strict=False)
            )
            # Dense official-road routes may contain many short turns. Their
            # settle windows and acceleration limits can dominate the simple
            # distance/speed estimate, so budget both distance and point count.
            timeout_seconds = max(
                300.0,
                route_distance / max(0.5, args.velocity_m_s) * 3.0 + 180.0,
                len(points) * 8.0 + 180.0,
            )
            executor = subprocess.Popen(
                [
                    sys.executable,
                    str(executor_path),
                    "--run-dir",
                    str(run_dir),
                    "--track",
                    str(track_path),
                    "--params",
                    str(params_path),
                    "--vehicle",
                    autopilot_model,
                    "--world",
                    support.WORLD_NAME,
                    "--abort-file",
                    str(run_dir / "live_abort.request.json"),
                    "--runtime-control-file",
                    str(run_dir / "runtime_control.request.json"),
                    "--setpoint-rate-hz",
                    "20",
                    "--takeoff-timeout-seconds",
                    "300",
                    "--takeoff-climb-rate-m-s",
                    "0.7",
                    "--track-timeout-seconds",
                    f"{timeout_seconds:g}",
                    "--landing-timeout-seconds",
                    "90",
                    "--takeoff-stable-window-seconds",
                    "1.5",
                    "--log",
                    str(run_dir / "offboard_executor.log"),
                ],
                env=env,
                stdout=executor_stdout,
                stderr=executor_stderr,
                text=True,
                start_new_session=True,
            )
            return_code = executor.wait(timeout=timeout_seconds + 420)
            time.sleep(4)
            if recorder is not None:
                recorder.stop()
            samples = recorder.samples if recorder is not None else []
            unsafe = collision_count(samples, semantic, vehicle)
            maximum_z = max((sample.model_root_z for sample in samples), default=0.0)
            final = samples[-1] if samples else None
            returned = (
                final is not None
                and math.dist((final.model_root_x, final.model_root_y), spawn[:2]) <= 1.0
            )
            landed = final is not None and abs(final.model_root_z - spawn[2]) <= 0.25
            accepted = (
                return_code == 0
                and len(samples) >= 25
                and maximum_z >= args.cruise_altitude_m - 1.5
                and returned
                and landed
                and unsafe == 0
            )
            evidence = {
                "schema_version": "dronedream.helsinki-map-px4-mission-evidence.v1",
                "asset_id": semantic["asset_id"],
                "scene_id": semantic["scene_id"],
                "source": "real-gazebo-harmonic-px4-sitl",
                "accepted": accepted,
                "executor_exit_code": return_code,
                "pose_sample_count": len(samples),
                "maximum_model_root_z_m": maximum_z,
                "returned_to_launch": returned,
                "landed": landed,
                "unsafe_collision_count": unsafe,
                "route_distance_m": route_distance,
                "route_waypoint_count": len(points),
                "gazebo_version": "8.15.0",
                "px4_root": str(px4_root),
                "vehicle": args.vehicle_model,
                "natural_language_acceptance": False,
                "artifacts": {
                    "qualification_inputs": "qualification-inputs.json",
                    "route": "mission-route.json",
                    "track": "reference_track.json",
                    "poses": "gazebo_pose_samples.csv",
                    "px4_log": "px4.log",
                    "gazebo_log": "gazebo.log",
                    "executor_log": "offboard_executor.log",
                },
            }
            write_json(run_dir / "mission_evidence.json", evidence)
            print(json.dumps(evidence, ensure_ascii=False))
            return 0 if accepted else 1
        finally:
            if recorder is not None:
                recorder.stop()
            for process in (executor, px4, gazebo):
                if process is not None:
                    support._terminate_process_group(process)


if __name__ == "__main__":
    raise SystemExit(main())
