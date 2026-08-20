from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _descriptor(
    engine: str,
    bridge: str,
    *,
    configuration: dict[str, object],
    **_: Any,
) -> dict[str, object]:
    return {
        "engine": engine,
        "bridge": bridge,
        "headless": bool(configuration.get("headless", True)),
        "deterministic_seed_supported": True,
        "runtime_probe_required": True,
    }


def _physics(*, configuration: dict[str, object], **_: Any) -> dict[str, object]:
    return {
        "solver": str(configuration.get("solver", "dart")),
        "step_seconds": float(configuration.get("step_seconds", 0.001)),
        "real_time_factor_target": float(configuration.get("real_time_factor_target", 1.0)),
        "contact_tolerance_m": float(configuration.get("contact_tolerance_m", 0.0005)),
    }


def _sensor_noise(**_: Any) -> dict[str, object]:
    return {
        "models": ["imu-bias-random-walk", "gnss-noise", "barometer-drift", "camera-latency"],
        "seed_bound": True,
    }


def _weather_light(**_: Any) -> dict[str, object]:
    return {
        "models": ["wind", "rain", "fog", "illumination", "sun-angle"],
        "scenario_bound": True,
    }


def _crowd_traffic(**_: Any) -> dict[str, object]:
    return {
        "models": ["pedestrian-flow", "vehicle-traffic", "door-state", "elevator-state"],
        "dynamic_obstacles": True,
    }


def _sim_clock(**_: Any) -> dict[str, object]:
    return {"source": "sim-time", "pause_aware": True, "maximum_skew_ms": 10}


def _monte_carlo(**_: Any) -> dict[str, object]:
    return {
        "seed_strategy": "prime-sequence",
        "minimum_runs": 3,
        "failure_reproduction": True,
        "aggregate": ["success-rate", "minimum-clearance", "energy", "latency"],
    }


def plugin_definitions() -> list[PluginDefinition]:
    definitions: list[PluginDefinition] = []
    for order, (plugin_id, name, engine, bridge, enabled) in enumerate(
        [
            ("simulation.engine-gazebo", "Gazebo Harmonic", "gazebo-harmonic", "ros-gz", True),
            ("simulation.engine-isaac", "NVIDIA Isaac Sim", "isaac-sim", "omni-ros2", False),
            ("simulation.engine-airsim", "AirSim", "airsim", "airsim-ros2", False),
            ("simulation.engine-webots", "Webots", "webots", "webots-ros2", False),
        ],
        start=1,
    ):

        def handler(
            *,
            configuration: dict[str, object],
            _engine: str = engine,
            _bridge: str = bridge,
            **kwargs: Any,
        ) -> dict[str, object]:
            return _descriptor(_engine, _bridge, configuration=configuration, **kwargs)

        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=f"描述并验证 {name} 的时钟、种子和 ROS 2 桥接能力。",
                capability_id=f"{plugin_id}.describe",
                capability_kind="simulator-adapter",
                capability_name=name,
                capability_description=f"{name} 仿真器适配合同。",
                category_id="simulation",
                category_label="仿真与测试",
                slot_id="simulation.simulator-descriptor",
                slot_label="仿真器",
                activation_mode="single",
                category_order=80,
                slot_order=10,
                plugin_order=order * 10,
                hooks={"describe_simulator": handler},
                default_enabled=enabled,
                failure_mode="fail-closed",
                configuration_schema={
                    "type": "object",
                    "properties": {"headless": {"type": "boolean", "default": True}},
                    "additionalProperties": False,
                },
            )
        )
    multiple = [
        (
            "simulation.physics-dart",
            "DART 物理",
            "physics-model",
            "simulation.physics-models",
            "物理模型",
            "describe_physics",
            _physics,
            10,
        ),
        (
            "simulation.sensor-noise",
            "传感器噪声",
            "sensor-model",
            "simulation.sensor-models",
            "传感器模型",
            "describe_sensor",
            _sensor_noise,
            20,
        ),
        (
            "simulation.weather-light",
            "天气与光照",
            "environment-model",
            "simulation.environment-models",
            "环境模型",
            "describe_environment",
            _weather_light,
            30,
        ),
        (
            "simulation.crowd-traffic",
            "人群与交通",
            "environment-model",
            "simulation.environment-models",
            "环境模型",
            "describe_environment",
            _crowd_traffic,
            40,
        ),
    ]
    for plugin_id, name, kind, slot_id, slot_label, hook, handler, order in multiple:
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=f"为仿真任务提供可冻结的{name}参数。",
                capability_id=f"{plugin_id}.{hook}",
                capability_kind=kind,
                capability_name=name,
                capability_description=f"{name}合同。",
                category_id="simulation",
                category_label="仿真与测试",
                slot_id=slot_id,
                slot_label=slot_label,
                activation_mode="multiple",
                category_order=80,
                slot_order=40,
                plugin_order=order,
                hooks={hook: handler},
                default_enabled=True,
                failure_mode="isolate",
            )
        )
    for plugin_id, name, kind, slot_id, hook, handler, order in [
        (
            "simulation.clock-sim-time",
            "仿真时钟",
            "clock-policy",
            "simulation.clock-policy",
            "resolve_clock",
            _sim_clock,
            10,
        ),
        (
            "simulation.monte-carlo-prime",
            "Monte Carlo 素数种子",
            "monte-carlo-policy",
            "simulation.monte-carlo-policy",
            "resolve_monte_carlo",
            _monte_carlo,
            20,
        ),
    ]:
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=f"提供{name}的可复现策略。",
                capability_id=f"{plugin_id}.{hook}",
                capability_kind=kind,
                capability_name=name,
                capability_description=f"{name}策略。",
                category_id="simulation",
                category_label="仿真与测试",
                slot_id=slot_id,
                slot_label=name,
                activation_mode="single",
                category_order=80,
                slot_order=50,
                plugin_order=order,
                hooks={hook: handler},
                default_enabled=True,
                failure_mode="fail-closed",
            )
        )
    return definitions
