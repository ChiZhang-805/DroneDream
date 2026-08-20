from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _descriptor(name: str, capabilities: list[str], **_: Any) -> dict[str, object]:
    return {
        "implementation": name,
        "capabilities": capabilities,
        "native_abi": "dronedream.capability-plugin.v1",
        "core_authorization_required": True,
    }


def _watchdog(*, configuration: dict[str, object], **_: Any) -> dict[str, object]:
    return {
        "deadline_ms": int(configuration.get("deadline_ms", 250)),
        # Gazebo and the typed pose observer start before flight authority is granted.
        # This bound covers simulator startup; the 250 ms deadline applies after the
        # first observation and remains the airborne fail-closed gate.
        "startup_deadline_ms": int(configuration.get("startup_deadline_ms", 30_000)),
        "heartbeat_ms": int(configuration.get("heartbeat_ms", 25)),
        "on_miss": "safe-hold-then-land",
        "fail_closed": True,
    }


def plugin_definitions() -> list[PluginDefinition]:
    definitions: list[PluginDefinition] = []
    singles = [
        (
            "native.transport-px4",
            "PX4 uXRCE-DDS",
            "transport",
            "native.transport",
            "飞控传输",
            "transport_message",
            lambda **kwargs: _descriptor(
                "px4-uxrce-dds", ["offboard", "vehicle-command", "timesync"], **kwargs
            ),
            True,
            10,
        ),
        (
            "native.transport-ardupilot",
            "ArduPilot DDS/MAVLink",
            "transport",
            "native.transport",
            "飞控传输",
            "transport_message",
            lambda **kwargs: _descriptor(
                "ardupilot-dds-mavlink", ["guided", "mission", "timesync"], **kwargs
            ),
            False,
            20,
        ),
        (
            "native.estimator-ekf2",
            "EKF2 状态估计",
            "state-estimator",
            "native.state-estimator",
            "状态估计",
            "estimate_state",
            lambda **kwargs: _descriptor(
                "ekf2", ["imu", "gnss", "barometer", "magnetometer"], **kwargs
            ),
            True,
            10,
        ),
        (
            "native.estimator-factor-graph",
            "因子图状态估计",
            "state-estimator",
            "native.state-estimator",
            "状态估计",
            "estimate_state",
            lambda **kwargs: _descriptor("factor-graph", ["imu", "vio", "uwb", "lidar"], **kwargs),
            False,
            20,
        ),
        (
            "native.localization-gnss-vio-slam",
            "GNSS/VIO/SLAM 融合定位",
            "localization",
            "native.localization",
            "定位",
            "localize",
            lambda **kwargs: _descriptor(
                "gnss-vio-slam", ["gnss", "vio", "slam", "uwb", "frame-transform"], **kwargs
            ),
            True,
            10,
        ),
        (
            "native.controller-mpc",
            "约束 MPC 控制器",
            "controller",
            "native.controller",
            "飞行控制器",
            "control_policy",
            lambda **kwargs: _descriptor(
                "bounded-mpc", ["position", "velocity", "landing", "collision-brake"], **kwargs
            ),
            True,
            10,
        ),
    ]
    for plugin_id, name, kind, slot_id, slot_label, hook, handler, enabled, order in singles:
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=f"通过原生类型 ABI 提供{name}，运行期变更需认证安装。",
                capability_id=f"{plugin_id}.{hook}",
                capability_kind=kind,
                capability_name=name,
                capability_description=f"{name}原生运行时合同。",
                category_id="native",
                category_label="ROS 2 与飞控",
                slot_id=slot_id,
                slot_label=slot_label,
                activation_mode="single",
                category_order=75,
                slot_order=order,
                plugin_order=order,
                hooks={hook: handler},
                default_enabled=enabled,
                failure_mode="fail-closed",
                swap_policy="certified-update",
                permissions=["ros.read", "ros.write", "telemetry.read"],
            )
        )
    multiples = [
        (
            "native.telemetry-core",
            "核心遥测",
            "telemetry-adapter",
            "native.telemetry",
            "遥测",
            "normalize_telemetry",
            ["pose", "velocity", "battery", "link", "flight-mode"],
            10,
        ),
        (
            "native.perception-obstacles",
            "障碍感知",
            "perception",
            "native.perception",
            "感知",
            "normalize_telemetry",
            ["depth", "lidar", "occupancy", "dynamic-track"],
            20,
        ),
        (
            "native.payload-gripper",
            "抓取与挂载",
            "payload-driver",
            "native.payload-drivers",
            "载荷驱动",
            "payload_command",
            ["attach", "detach", "load-cell", "identity"],
            30,
        ),
        (
            "native.payload-gimbal",
            "云台与相机",
            "payload-driver",
            "native.payload-drivers",
            "载荷驱动",
            "payload_command",
            ["gimbal", "photo", "video", "focus"],
            40,
        ),
        (
            "native.blackbox-rosbag-ulog",
            "ROS Bag 与 ULog 黑匣子",
            "evidence",
            "native.blackbox",
            "黑匣子",
            "normalize_telemetry",
            ["rosbag2", "mcap", "ulog", "hash-chain"],
            50,
        ),
    ]
    for plugin_id, name, kind, slot_id, slot_label, hook, capabilities, order in multiples:

        def handler(
            *, _name: str = plugin_id, _capabilities: list[str] = capabilities, **kwargs: Any
        ) -> dict[str, object]:
            return _descriptor(_name, _capabilities, **kwargs)

        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=f"可组合的{name}原生能力。",
                capability_id=f"{plugin_id}.{hook}",
                capability_kind=kind,
                capability_name=name,
                capability_description=f"{name}原生能力合同。",
                category_id="native",
                category_label="ROS 2 与飞控",
                slot_id=slot_id,
                slot_label=slot_label,
                activation_mode="multiple",
                category_order=75,
                slot_order=50,
                plugin_order=order,
                hooks={hook: handler},
                default_enabled=True,
                failure_mode="isolate",
                swap_policy="certified-update",
                permissions=["ros.read", "telemetry.read", "evidence.write"],
            )
        )
    definitions.append(
        hook_plugin(
            module_name=__name__,
            plugin_id="native.watchdog-deadline",
            name="实时截止时间看门狗",
            description="监控原生插件健康与截止时间，失约时强制安全悬停并降落。",
            capability_id="native.watchdog-deadline.resolve",
            capability_kind="runtime-watchdog",
            capability_name="实时截止时间看门狗",
            capability_description="原生运行时失效关闭策略。",
            category_id="native",
            category_label="ROS 2 与飞控",
            slot_id="native.watchdog",
            slot_label="实时看门狗",
            activation_mode="single",
            category_order=75,
            slot_order=60,
            plugin_order=10,
            hooks={"resolve_watchdog": _watchdog},
            default_enabled=True,
            failure_mode="fail-closed",
            swap_policy="certified-update",
            configuration_schema={
                "type": "object",
                "properties": {
                    "deadline_ms": {"type": "integer", "minimum": 20, "maximum": 1000},
                    "startup_deadline_ms": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 60000,
                    },
                    "heartbeat_ms": {"type": "integer", "minimum": 5, "maximum": 250},
                },
                "additionalProperties": False,
            },
            permissions=["ros.read", "ros.write", "telemetry.read"],
        )
    )
    return definitions
