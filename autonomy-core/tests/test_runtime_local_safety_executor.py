from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType

from dronedream_agent_core.contracts import (
    PredictiveSafetyDecision,
    Px4CoordinateContract,
    RuntimeLocalSafetyCommand,
    RuntimeLocalSafetyObservation,
    Vector3,
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
        "test_local_safety_base",
        root / "runtime" / "px4_offboard_track_executor.py",
    )
    executor = _load_module(
        "test_local_safety_executor",
        root / "scripts" / "px4_checkpoint_executor.py",
    )
    return base, executor


def _observation() -> RuntimeLocalSafetyObservation:
    return RuntimeLocalSafetyObservation(
        sequence=1,
        observed_at_unix_ms=int(time.time() * 1_000),
        source="simulation-ground-truth",
        stream_healthy=True,
        stream_age_seconds=0.0,
        localization_covariance_m2=0.0,
        current_position_m=Vector3(x=0.0, y=0.0, z=1.0),
        current_velocity_mps=Vector3(x=0.0, y=0.0, z=0.0),
        target_position_m=Vector3(x=2.0, y=0.0, z=1.0),
    )


def _command(
    observation: RuntimeLocalSafetyObservation,
    *,
    action: str,
) -> RuntimeLocalSafetyCommand:
    now = int(time.time() * 1_000)
    return RuntimeLocalSafetyCommand(
        observation_sha256=sha256_json(observation),
        observation_sequence=observation.sequence,
        generated_at_unix_ms=now,
        valid_until_unix_ms=now + 2_000,
        source=observation.source,
        command_position_m=Vector3(x=0.1, y=0.4, z=1.0),
        decision=PredictiveSafetyDecision(
            action=action,
            selected_velocity_mps=Vector3(x=0.5, y=0.5, z=0.0),
            predicted_path_m=[Vector3(x=0.1, y=0.4, z=1.0)],
            minimum_predicted_clearance_m=0.5,
            time_to_minimum_clearance_seconds=0.2,
            threat_obstacle_id="person-crossing",
            evaluated_candidate_count=10,
            issue_codes=[] if action == "continue" else ["LOCAL_SAFETY_REPLAN"],
        ),
    )


def test_executor_holds_schedule_index_during_local_repair(tmp_path: Path) -> None:
    base, executor = _modules()
    observation_path = tmp_path / "observation.json"
    command_path = tmp_path / "command.json"
    target_path = tmp_path / "target.json"
    phase_path = tmp_path / "phase.json"
    observation = _observation()
    observation_path.write_text(observation.model_dump_json(), encoding="utf-8")
    command_path.write_text(
        _command(observation, action="replan").model_dump_json(),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        local_safety_command=command_path,
        local_safety_observation=observation_path,
        local_safety_target=target_path,
        local_safety_repair_timeout_seconds=1.0,
        setpoint_rate_hz=50.0,
    )
    coordinate = Px4CoordinateContract(
        model_root_world_enu_m=[0.0, 0.0, 0.0],
        collision_center_above_model_root_m=0.2,
    )
    planned = base.Setpoint(north_m=0.0, east_m=2.0, down_m=-0.8, yaw_deg=0.0)
    client = base.FakeOffboardClient()

    async def exercise() -> None:
        async def clear_conflict() -> None:
            await asyncio.sleep(0.06)
            command_path.write_text(
                _command(observation, action="continue").model_dump_json(),
                encoding="utf-8",
            )

        update = asyncio.create_task(clear_conflict())
        await executor._apply_local_safety(
            args=args,
            base=base,
            client=client,
            planned_setpoint=planned,
            coordinate_contract=coordinate,
            phase_path=phase_path,
        )
        await update

    asyncio.run(exercise())

    assert len(client.setpoints) >= 2
    assert client.setpoints[0].north_m == 0.4
    assert client.setpoints[-1] == planned
    assert target_path.is_file()
    assert "LOCAL_REPLAN" in phase_path.read_text(encoding="utf-8")
