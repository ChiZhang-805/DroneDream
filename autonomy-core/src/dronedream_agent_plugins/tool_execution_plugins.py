from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _resilient(*, tool: dict[str, object], **_: Any) -> dict[str, object]:
    authority = tool.get("authority")
    return {
        "maximum_attempts": 2 if authority in {"read", "plan", "simulate"} else 1,
        "cache": authority in {"read", "plan"},
        "parallelism": 4,
        "provenance_required": True,
    }


def _strict_serial(**_: Any) -> dict[str, object]:
    return {
        "maximum_attempts": 1,
        "cache": False,
        "parallelism": 1,
        "provenance_required": True,
    }


def plugin_definitions() -> list[PluginDefinition]:
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.resolve",
            capability_kind="tool-execution-policy",
            capability_name=name,
            capability_description=description,
            category_id="tools",
            category_label="工具与集成",
            slot_id="tools.execution-policy",
            slot_label="工具执行策略",
            activation_mode="single",
            category_order=50,
            slot_order=20,
            plugin_order=order,
            hooks={"resolve_tool_execution": handler},
            default_enabled=enabled,
            failure_mode="fail-closed",
        )
        for plugin_id, name, description, handler, enabled, order in [
            (
                "tools.execution-resilient",
                "弹性并行执行",
                "为只读和规划工具提供有界重试、缓存、并行和来源收据。",
                _resilient,
                True,
                10,
            ),
            (
                "tools.execution-strict-serial",
                "严格串行执行",
                "关闭缓存与重试，逐个执行工具以便复现实验。",
                _strict_serial,
                False,
                20,
            ),
        ]
    ]
