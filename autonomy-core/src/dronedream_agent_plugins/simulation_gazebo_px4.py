from __future__ import annotations

from dronedream_agent_core.plugin_api import PluginDefinition
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="simulation.gazebo-px4",
            name="Gazebo PX4 Runtime",
            version="1.0.0",
            description="连接 Gazebo、PX4 SITL、ROS 2 与证据化任务执行器。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python",
                entrypoint=f"{__name__}:plugin_definition",
            ),
            capabilities=[
                PluginCapability(
                    capability_id="simulation.gazebo-px4.execute",
                    kind="runtime-adapter",
                    name="Gazebo PX4 任务执行",
                    description="在 DroneDreamRuntime 中执行冻结的 PX4 仿真任务。",
                    authority="control",
                    metadata={
                        "distribution": "DroneDreamRuntime",
                        "simulator": "Gazebo",
                        "autopilot": "PX4 SITL",
                        "middleware": "ROS 2 Jazzy",
                        "ros_domain_id": 74,
                        "ros_setup": "/opt/ros/jazzy/setup.bash",
                        "px4_root": "/opt/PX4-Autopilot",
                        "runtime_cli": "execute-prepared-mission",
                        "executor": "px4_offboard_track_executor.py",
                        "checkpoint_executor": "px4_checkpoint_executor.py",
                        "capability_host": "ros2 run dronedream_agent_plugin_api capability_host",
                    },
                )
            ],
            permissions=[
                "asset.read",
                "mission.read",
                "mission.write-output",
                "ros.read",
                "ros.write",
                "simulator.control",
            ],
            default_enabled=True,
            removable=False,
            disable_allowed=False,
            placement=PluginPlacement(
                category_id="simulation",
                category_label="仿真与运行时",
                slot_id="simulation.runtime-adapter",
                slot_label="仿真运行时",
                activation_mode="single",
                scope="runtime",
                category_order=40,
                slot_order=10,
                plugin_order=10,
            ),
        )
    )
