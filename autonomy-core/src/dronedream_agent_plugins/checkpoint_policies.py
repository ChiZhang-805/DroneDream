from __future__ import annotations

from typing import Any

from dronedream_agent_core.contracts import (
    FlightPlan,
    MissionContract,
    RuntimeCheckpoint,
    RuntimeCheckpointContract,
)
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _segment_checkpoints(
    *, contract: MissionContract, flight_plan: FlightPlan, **_: Any
) -> RuntimeCheckpointContract:
    checkpoints: list[RuntimeCheckpoint] = []
    track_index = 0
    for index, segment in enumerate(flight_plan.segments, start=1):
        track_index += len(segment.path) - 1
        checkpoints.append(
            RuntimeCheckpoint(
                checkpoint_id=f"checkpoint-{index:03d}",
                segment_id=segment.segment_id,
                task_id=segment.task_id,
                track_point_index=track_index,
                target_node=segment.to_node,
            )
        )
    return RuntimeCheckpointContract(contract_id=contract.contract_id, checkpoints=checkpoints)


def _mission_boundary_checkpoints(
    *, contract: MissionContract, flight_plan: FlightPlan, **_: Any
) -> RuntimeCheckpointContract:
    selected_indexes = {0, len(flight_plan.segments) - 1}
    checkpoints: list[RuntimeCheckpoint] = []
    track_index = 0
    for segment_index, segment in enumerate(flight_plan.segments):
        track_index += len(segment.path) - 1
        if segment_index not in selected_indexes:
            continue
        checkpoints.append(
            RuntimeCheckpoint(
                checkpoint_id=f"checkpoint-{len(checkpoints) + 1:03d}",
                segment_id=segment.segment_id,
                task_id=segment.task_id,
                track_point_index=track_index,
                target_node=segment.to_node,
            )
        )
    return RuntimeCheckpointContract(contract_id=contract.contract_id, checkpoints=checkpoints)


def plugin_definitions() -> list[PluginDefinition]:
    values = [
        (
            "runtime.checkpoint-every-segment",
            "逐航段检查",
            "在每个飞行航段终点请求遥测与模型检查，作为默认闭环策略。",
            _segment_checkpoints,
            True,
        ),
        (
            "runtime.checkpoint-mission-boundaries",
            "任务边界检查",
            "仅检查到达任务目标和返程终点，适合低风险、低延迟仿真。",
            _mission_boundary_checkpoints,
            False,
        ),
    ]
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.build",
            capability_kind="checkpoint-policy",
            capability_name=name,
            capability_description=description,
            category_id="runtime",
            category_label="运行时与闭环",
            slot_id="runtime.checkpoint-policy",
            slot_label="运行检查点策略",
            activation_mode="single",
            category_order=80,
            slot_order=10,
            plugin_order=index * 10,
            hooks={"build_checkpoints": handler},
            default_enabled=enabled,
            failure_mode="fail-closed",
            swap_policy="next-mission",
        )
        for index, (plugin_id, name, description, handler, enabled) in enumerate(values, start=1)
    ]
