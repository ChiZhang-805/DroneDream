from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _wait_for(
    path: Path,
    predicate: Any,
    *,
    timeout_seconds: float,
    label: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        value = _read_json(path)
        if value is not None and predicate(value):
            return value
        if value is not None and value.get("abort_reason"):
            raise RuntimeError(f"{label} aborted: {value['abort_reason']}")
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {label}")


def _replacement_route(
    reference_track: dict[str, Any], trigger: dict[str, Any]
) -> list[dict[str, Any]]:
    points = reference_track.get("points")
    if not isinstance(points, list) or len(points) != 73:
        raise ValueError("HOT_REPLAN_REFERENCE_TRACK_INVALID")
    outbound = points[:37]
    current_world = trigger.get("vehicle_envelope_center_world_enu_m")
    if not isinstance(current_world, list) or len(current_world) != 3:
        raise ValueError("HOT_REPLAN_CURRENT_POSITION_INVALID")
    current_local = {
        "x": float(current_world[1]) - 15.3,
        "y": float(current_world[0]) + 42.25,
        "z": float(current_world[2]) - 7.715,
        "speed_limit_mps": 0.65,
    }
    route_source = [current_local, outbound[32], outbound[33], *reversed(outbound[:33])]
    route: list[dict[str, Any]] = []
    for index, source in enumerate(route_source):
        if not isinstance(source, dict):
            raise ValueError("HOT_REPLAN_REFERENCE_TRACK_INVALID")
        phase = "transit" if index < 2 else "return"
        if index == len(route_source) - 1:
            phase = "land"
        route.append(
            {
                "x": float(source["x"]),
                "y": float(source["y"]),
                "z": float(source["z"]),
                "phase": phase,
                "speed_limit_mps": float(source["speed_limit_mps"]),
            }
        )
    return route


def _minimum_destination_distance(pose_path: Path) -> float:
    target = (30.0, -18.0, 1.8)
    minimum = math.inf
    with pose_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            position = (
                float(row["envelope_center_east_m"]),
                float(row["envelope_center_north_m"]),
                float(row["envelope_center_up_m"]),
            )
            minimum = min(minimum, math.dist(position, target))
    if not math.isfinite(minimum):
        raise ValueError("HOT_REPLAN_POSE_EVIDENCE_EMPTY")
    return minimum


def run(run_dir: Path, *, timeout_seconds: float) -> dict[str, Any]:
    status_path = run_dir / "mission_live_status.json"
    control_path = run_dir / "runtime_control.request.json"
    ack_path = run_dir / "runtime_control.ack.json"
    contract_id = run_dir.name
    trigger = _wait_for(
        status_path,
        lambda value: (
            value.get("status") == "running"
            and value.get("phase") == "transit"
            and 30 <= int(value.get("route_index", -1)) <= 33
            and value.get("payload_attached") is False
        ),
        timeout_seconds=timeout_seconds,
        label="safe outdoor interruption point",
    )
    hold_request = {
        "schema_version": "dronedream.autonomy.runtime-control.v1",
        "revision": 1,
        "mission_revision": 1,
        "contract_id": contract_id,
        "action": "hold",
    }
    _write_json_atomic(control_path, hold_request)
    hold_ack = _wait_for(
        ack_path,
        lambda value: value.get("revision") == 1 and value.get("state") == "holding",
        timeout_seconds=30.0,
        label="PX4 hold acknowledgement",
    )
    stable_samples: list[dict[str, Any]] = []
    last_telemetry_sample_elapsed_s: float | None = None
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and len(stable_samples) < 3:
        current = _read_json(status_path)
        telemetry_sample_elapsed_s = (
            float(current.get("telemetry_sample_elapsed_s", math.nan))
            if current is not None
            else math.nan
        )
        if (
            current is not None
            and math.isfinite(telemetry_sample_elapsed_s)
            and telemetry_sample_elapsed_s != last_telemetry_sample_elapsed_s
            and float(current.get("vehicle_speed_m_s", math.inf)) <= 0.12
        ):
            stable_samples.append(
                {
                    "observed_at": time.time(),
                    "telemetry_sample_elapsed_s": telemetry_sample_elapsed_s,
                    "vehicle_speed_m_s": float(current["vehicle_speed_m_s"]),
                    "vehicle_envelope_center_world_enu_m": current.get(
                        "vehicle_envelope_center_world_enu_m"
                    ),
                }
            )
            last_telemetry_sample_elapsed_s = telemetry_sample_elapsed_s
        elif (
            current is not None
            and math.isfinite(telemetry_sample_elapsed_s)
            and telemetry_sample_elapsed_s != last_telemetry_sample_elapsed_s
        ):
            stable_samples.clear()
            last_telemetry_sample_elapsed_s = telemetry_sample_elapsed_s
        time.sleep(0.25)
    if len(stable_samples) < 3:
        raise TimeoutError("PX4 safe hold did not stabilize below 0.12 m/s")

    reference_track = _wait_for(
        run_dir / "reference_track.json",
        lambda value: isinstance(value.get("points"), list),
        timeout_seconds=5.0,
        label="reference track",
    )
    replacement = _replacement_route(reference_track, trigger)
    replace_request = {
        "schema_version": "dronedream.autonomy.runtime-control.v1",
        "revision": 2,
        "mission_revision": 2,
        "contract_id": contract_id,
        "action": "replace_route",
        "route": replacement,
    }
    _write_json_atomic(control_path, replace_request)
    replace_ack = _wait_for(
        ack_path,
        lambda value: (
            value.get("revision") == 2 and value.get("state") == "route_replaced"
        ),
        timeout_seconds=30.0,
        label="PX4 replacement-route acknowledgement",
    )
    mission = _wait_for(
        run_dir / "mission_evidence.json",
        lambda value: value.get("status") in {"verified", "failed"},
        timeout_seconds=timeout_seconds,
        label="mission completion evidence",
    )
    timing = _wait_for(
        run_dir / "offboard_timing.json",
        lambda value: value.get("status") == "complete",
        timeout_seconds=10.0,
        label="offboard timing evidence",
    )
    runtime_actions = [
        event.get("action")
        for event in timing.get("runtime_controls", [])
        if isinstance(event, dict)
    ]
    gates = mission.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("HOT_REPLAN_MISSION_GATES_INVALID")
    destination_distance = _minimum_destination_distance(
        run_dir / "gazebo_pose_samples.csv"
    )
    assertions = {
        "interrupted_before_original_pickup": trigger.get("payload_attached") is False,
        "hold_acknowledged": hold_ack.get("state") == "holding",
        "safe_hold_stabilized": max(
            float(sample["vehicle_speed_m_s"]) for sample in stable_samples
        )
        <= 0.12,
        "route_replacement_acknowledged": replace_ack.get("state")
        == "route_replaced",
        "hold_and_replace_recorded": runtime_actions == ["hold", "replace_route"],
        "changed_destination_reached": destination_distance <= 0.5,
        "executor_completed": gates.get("executor_completed") is True,
        "offboard_timing_complete": gates.get("offboard_timing_complete") is True,
        "office_return_reached": gates.get("office_return_reached") is True,
        "landed_on_office_pad": gates.get("landed_on_office_pad") is True,
        "px4_landing_confirmed": gates.get("px4_landing_confirmed") is True,
        "zero_unsafe_dynamic_penetrations": gates.get(
            "zero_unsafe_dynamic_penetrations"
        )
        is True,
    }
    evidence = {
        "schema_version": "dronedream.school-map-hot-replan-evidence.v1",
        "status": "verified" if all(assertions.values()) else "failed",
        "contract_id": contract_id,
        "assertions": assertions,
        "trigger": trigger,
        "hold_request": hold_request,
        "hold_ack": hold_ack,
        "stable_hold_samples": stable_samples,
        "replacement_request": replace_request,
        "replacement_ack": replace_ack,
        "runtime_control_actions": runtime_actions,
        "measurements": {
            "minimum_changed_destination_distance_m": destination_distance,
            "maximum_stabilized_hold_speed_m_s": max(
                float(sample["vehicle_speed_m_s"]) for sample in stable_samples
            ),
        },
        "source_mission_status": mission.get("status"),
        "source_mission_evidence": "mission_evidence.json",
        "offboard_timing_evidence": "offboard_timing.json",
    }
    _write_json_atomic(run_dir / "hot_replan_evidence.json", evidence)
    if evidence["status"] != "verified":
        raise AssertionError(
            "HOT_REPLAN_ACCEPTANCE_FAILED:" + json.dumps(assertions, sort_keys=True)
        )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=1_800.0)
    args = parser.parse_args()
    evidence = run(args.run_dir.resolve(), timeout_seconds=args.timeout_seconds)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
