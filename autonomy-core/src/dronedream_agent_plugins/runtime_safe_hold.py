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
            plugin_id="runtime.safe-hold",
            name="安全悬停内核",
            version="1.0.0",
            description="在处理运行中用户消息前冻结旧航迹并验证稳定悬停。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python",
                entrypoint=f"{__name__}:plugin_definition",
            ),
            capabilities=[
                PluginCapability(
                    capability_id="runtime.safe-hold.interrupt",
                    kind="runtime-adapter",
                    name="运行中安全打断",
                    description="抑制旧计划副作用并进入遥测确认的安全悬停。",
                    authority="control",
                    metadata={
                        "policy": "safe-hold-before-classification",
                        "immediate_action": "safe_hold",
                        "hold_timeout_seconds": 12.0,
                        "replan_hold_seconds": 30.0,
                    },
                )
            ],
            permissions=["mission.read", "mission.write-output", "ros.read", "ros.write"],
            default_enabled=True,
            removable=False,
            disable_allowed=False,
            placement=PluginPlacement(
                category_id="safety",
                category_label="安全与验证",
                slot_id="safety.interruption-policy",
                slot_label="运行中打断策略",
                activation_mode="single",
                scope="runtime",
                category_order=10,
                slot_order=20,
                plugin_order=10,
            ),
        )
    )
