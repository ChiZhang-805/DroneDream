from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from dronedream_agent_core.contracts import (
    Px4CoordinateContract,
    RuntimeOperatorControlCommand,
    RuntimeOperatorTakeoverGrant,
    Vector3,
    VehicleAsset,
)
from dronedream_agent_core.hashing import sha256_json


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _modules() -> tuple[ModuleType, ModuleType]:
    root = Path(__file__).parents[1]
    base = _load_module(
        "test_runtime_follow_base",
        root / "runtime" / "px4_offboard_track_executor.py",
    )
    executor = _load_module(
        "test_runtime_follow_executor",
        root / "scripts" / "px4_checkpoint_executor.py",
    )
    return base, executor


def _write_assets(tmp_path: Path, *, collision_x: float = 100.0) -> tuple[Path, Path]:
    semantic = tmp_path / "semantic.json"
    semantic.write_text(
        json.dumps(
            {
                "collision_primitives": [
                    {
                        "name": "wall",
                        "center_x": collision_x,
                        "center_y": 0.0,
                        "center_z": 1.0,
                        "size_x": 0.05,
                        "size_y": 0.05,
                        "size_z": 2.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    vehicle = tmp_path / "vehicle.json"
    vehicle.write_text(
        VehicleAsset(
            asset_id="follow-test-drone",
            name="Follow Test Drone",
            dry_mass_kg=1.0,
            max_takeoff_mass_kg=2.0,
            body_radius_m=0.2,
            body_height_m=0.2,
            max_speed_mps=3.0,
            max_acceleration_mps2=2.0,
            qualified_range_m=500.0,
            reserve_battery_percent=20.0,
            max_pickup_payload_kg=0.5,
            sensors=["camera"],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    return semantic, vehicle


def _args(tmp_path: Path, semantic: Path, vehicle: Path) -> argparse.Namespace:
    control_dir = tmp_path / "runtime-control"
    control_dir.mkdir(parents=True)
    return argparse.Namespace(
        semantic=semantic,
        vehicle_metadata=vehicle,
        runtime_control_dir=control_dir,
        abort_file=tmp_path / "abort.json",
        setpoint_rate_hz=20.0,
        runtime_hold_timeout_seconds=1.0,
        runtime_decision_timeout_seconds=1.0,
        runtime_replan_hold_seconds=1.0,
    )


def _replacement(executor: ModuleType, base: ModuleType) -> Any:
    return executor.RuntimeTrackReplacement(
        message_id="runtime-msg-" + "a" * 32,
        schedule=[],
        track_sha256="1" * 64,
        replacement_sequence=1,
        amendment_action="follow_target",
        amendment_parameters={
            "target_pose_topic": "/model/person/pose",
            "target_model_name": "person",
            "follow_duration_seconds": 1.0,
            "target_update_rate_hz": 10.0,
            "standoff_m": 0.5,
            "altitude_offset_m": 1.0,
            "maximum_speed_mps": 3.0,
        },
        coordinate_contract=Px4CoordinateContract(
            model_root_world_enu_m=[0.0, 0.0, 0.0],
            collision_center_above_model_root_m=0.2,
        ),
    )


def test_dynamic_follow_samples_target_rechecks_clearance_and_writes_evidence(
    tmp_path: Path,
) -> None:
    base, executor = _modules()
    semantic, vehicle = _write_assets(tmp_path)
    args = _args(tmp_path, semantic, vehicle)
    client = base.FakeOffboardClient()
    client.gazebo_pose_samples = [
        {"x": 2.0, "y": 0.0, "z": 0.0, "topic": "/model/person/pose"},
        {"x": 2.2, "y": 0.1, "z": 0.0, "topic": "/model/person/pose"},
        {"x": 2.4, "y": 0.2, "z": 0.0, "topic": "/model/person/pose"},
    ]
    initial = base.Setpoint(north_m=0.0, east_m=0.0, down_m=-0.8, yaw_deg=0.0)
    timing: dict[str, Any] = {"runtime_interruptions": []}

    final = asyncio.run(
        executor._follow_runtime_target(
            args=args,
            base=base,
            client=client,
            params=argparse.Namespace(),
            runtime_session=None,
            replacement=_replacement(executor, base),
            initial_setpoint=initial,
            phase_path=tmp_path / "phase.json",
            timing=timing,
        )
    )

    evidence_path = (
        args.runtime_control_dir / "follow" / ("runtime-msg-" + "a" * 32 + ".evidence.json")
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "complete"
    assert len(evidence["observations"]) >= 3
    assert all(item["clearance_sha256"] for item in evidence["observations"])
    assert len(client.setpoints) >= 15
    assert final.east_m > initial.east_m
    assert timing["runtime_interruptions"][-1]["outcome"] == "follow_target_complete"


def test_dynamic_follow_collision_fails_closed_with_evidence(tmp_path: Path) -> None:
    base, executor = _modules()
    semantic, vehicle = _write_assets(tmp_path, collision_x=0.1)
    args = _args(tmp_path, semantic, vehicle)
    client = base.FakeOffboardClient()
    client.gazebo_pose_samples = [{"x": 2.0, "y": 0.0, "z": 0.0, "topic": "/model/person/pose"}]
    initial = base.Setpoint(north_m=0.0, east_m=0.0, down_m=-0.8, yaw_deg=0.0)

    with pytest.raises(executor.UserDirectedLanding, match="clearance gate rejected"):
        asyncio.run(
            executor._follow_runtime_target(
                args=args,
                base=base,
                client=client,
                params=argparse.Namespace(),
                runtime_session=None,
                replacement=_replacement(executor, base),
                initial_setpoint=initial,
                phase_path=tmp_path / "phase.json",
                timing={"runtime_interruptions": []},
            )
        )

    evidence_path = (
        args.runtime_control_dir / "follow" / ("runtime-msg-" + "a" * 32 + ".evidence.json")
    )
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["status"] == "failed"


def test_operator_takeover_accepts_bounded_velocity_then_release_lands(tmp_path: Path) -> None:
    base, executor = _modules()
    semantic, vehicle_path = _write_assets(tmp_path)
    control_dir = tmp_path / "runtime-control"
    command_dir = control_dir / "operator-commands"
    command_dir.mkdir(parents=True)
    now = datetime.now(UTC)
    message_id = "runtime-msg-" + "b" * 32
    execution_id = "execution-" + "c" * 32
    grant = RuntimeOperatorTakeoverGrant(
        message_id=message_id,
        execution_id=execution_id,
        operator_id="operator-a",
        message_sha256="1" * 64,
        hold_ack_sha256="2" * 64,
        decision_sha256="3" * 64,
        grant_token_sha256="4" * 64,
        maximum_horizontal_speed_mps=1.5,
        maximum_vertical_speed_mps=1.0,
        maximum_yaw_rate_dps=90.0,
        deterministic_gates={"stable_hold": True, "local_session": True},
        issued_at=now,
        expires_at=now + timedelta(seconds=10),
    )
    grant_hash = sha256_json(grant)
    velocity = RuntimeOperatorControlCommand(
        message_id=message_id,
        execution_id=execution_id,
        grant_sha256=grant_hash,
        sequence=1,
        action="velocity",
        velocity_ned_mps=Vector3(x=0.5, y=0.5, z=0.0),
        yaw_rate_dps=10.0,
        duration_seconds=0.1,
        issued_at=datetime.now(UTC),
    )
    release = RuntimeOperatorControlCommand(
        message_id=message_id,
        execution_id=execution_id,
        grant_sha256=grant_hash,
        sequence=2,
        action="release",
        yaw_rate_dps=0.0,
        duration_seconds=0.1,
        issued_at=datetime.now(UTC),
    )
    (command_dir / "00000001.json").write_text(velocity.model_dump_json(indent=2), encoding="utf-8")
    (command_dir / "00000002.json").write_text(release.model_dump_json(indent=2), encoding="utf-8")
    client = base.FakeOffboardClient()
    initial = base.Setpoint(north_m=0.0, east_m=0.0, down_m=-0.8, yaw_deg=0.0)
    coordinate_contract = Px4CoordinateContract(
        model_root_world_enu_m=[0.0, 0.0, 0.0],
        collision_center_above_model_root_m=0.2,
    )
    interruption = SimpleNamespace(message=SimpleNamespace(message_id=message_id))

    with pytest.raises(executor.UserDirectedLanding, match="released takeover"):
        asyncio.run(
            executor._run_operator_takeover(
                base=base,
                client=client,
                hold_setpoint=initial,
                interruption=interruption,
                grant=grant,
                control_dir=control_dir,
                abort_file=tmp_path / "abort.json",
                rate_hz=20.0,
                runtime_session=None,
                active_track_sha256="5" * 64,
                params=argparse.Namespace(),
                hold_timeout_seconds=1.0,
                decision_timeout_seconds=1.0,
                replan_hold_seconds=1.0,
                semantic_path=semantic,
                vehicle_metadata_path=vehicle_path,
                coordinate_contract=coordinate_contract,
            )
        )

    assert (control_dir / "processed-operator-commands" / "00000001.json").is_file()
    assert (control_dir / "processed-operator-commands" / "00000002.json").is_file()
    assert (control_dir / "takeover-adoptions" / f"{message_id}.json").is_file()
    evidence = json.loads(
        (control_dir / "takeover-evidence" / f"{message_id}.json").read_text(encoding="utf-8")
    )
    assert evidence["status"] == "released"
    assert len(evidence["commands"]) == 2
    assert len(client.setpoints) >= 2
