from __future__ import annotations

import math
from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin

SENSITIVE_KEY_PARTS = ("api_key", "apikey", "authorization", "password", "secret")


def _secret_guard(*, value: dict[str, object], **_: Any) -> dict[str, object]:
    def walk(current: object, path: tuple[str, ...] = ()) -> None:
        if isinstance(current, dict):
            for key, item in current.items():
                normalized = str(key).casefold().replace("-", "_")
                if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                    raise ValueError("TOOL_ARGUMENT_CONTAINS_SECRET:" + ".".join((*path, str(key))))
                walk(item, (*path, str(key)))
        elif isinstance(current, list):
            for index, item in enumerate(current):
                walk(item, (*path, str(index)))

    walk(value)
    return value


def _finite_number_guard(*, value: dict[str, object], **_: Any) -> dict[str, object]:
    def walk(current: object) -> None:
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError("TOOL_ARGUMENT_NON_FINITE")
        if isinstance(current, dict):
            for item in current.values():
                walk(item)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(value)
    return value


def _output_guard(*, value: dict[str, object], **_: Any) -> dict[str, object]:
    if any(str(key).startswith("_") for key in value):
        raise ValueError("TOOL_OUTPUT_PRIVATE_FIELD")
    return value


def plugin_definitions() -> list[PluginDefinition]:
    values = [
        (
            "tools.middleware-secret-guard",
            "工具密钥隔离",
            "拒绝把 API Key、密码、Authorization 或 secret 字段传给任务工具。",
            "before_tool_call",
            _secret_guard,
            10,
        ),
        (
            "tools.middleware-finite-numbers",
            "有限数值检查",
            "拒绝 NaN 与无穷数进入导航、仿真和评测工具。",
            "before_tool_call",
            _finite_number_guard,
            20,
        ),
        (
            "tools.middleware-output-boundary",
            "工具输出边界",
            "拒绝工具输出以下划线开头的内部字段。",
            "after_tool_call",
            _output_guard,
            30,
        ),
    ]
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.filter",
            capability_kind="tool-middleware",
            capability_name=name,
            capability_description=description,
            category_id="tools",
            category_label="工具与集成",
            slot_id="tools.middleware",
            slot_label="工具调用管线",
            activation_mode="pipeline",
            category_order=50,
            slot_order=30,
            plugin_order=order,
            pipeline_order=order,
            hooks={hook: handler},
            default_enabled=True,
            failure_mode="fail-closed",
            swap_policy="next-mission",
        )
        for plugin_id, name, description, hook, handler, order in values
    ]
