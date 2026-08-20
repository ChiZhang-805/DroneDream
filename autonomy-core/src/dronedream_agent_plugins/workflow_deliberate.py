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
            plugin_id="workflow.deliberate",
            name="审慎规划流程",
            version="1.0.0",
            description="为复杂室内、载荷和高不确定性任务增加意图与插件路由审查。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definition"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="workflow.deliberate.policy",
                    kind="workflow-policy",
                    name="审慎规划",
                    description="五轮意图审查、五轮规划修复和三轮工具路由。",
                    authority="plan",
                    metadata={
                        "max_intent_rounds": 5,
                        "max_planning_rounds": 5,
                        "plugin_router_rounds": 3,
                        "maximum_plugin_calls": 12,
                        "intent_reviews_per_round": 2,
                        "plan_reviews_per_round": 2,
                    },
                )
            ],
            permissions=["mission.read"],
            default_enabled=False,
            removable=False,
            placement=PluginPlacement(
                category_id="planning",
                category_label="任务规划",
                slot_id="planning.workflow-policy",
                slot_label="规划工作流",
                activation_mode="single",
                scope="mission",
                category_order=20,
                slot_order=20,
                plugin_order=20,
            ),
        )
    )
