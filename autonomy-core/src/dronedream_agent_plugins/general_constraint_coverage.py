from __future__ import annotations

from dronedream_agent_core.plugin_api import PluginDefinition, ToolEnvironment
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)
from dronedream_agent_core.tools import ToolPlugin

INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["constraints"],
    "properties": {"constraints": {"type": "array", "items": {"type": "string"}}},
}
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["covered", "missing", "coverage_ratio"],
    "properties": {
        "covered": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "coverage_ratio": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def _coverage(value: dict[str, object]) -> dict[str, object]:
    rendered = " ".join(str(item).lower() for item in value.get("constraints", []))
    dimensions = {
        "safety priority": ("safe", "安全"),
        "return behavior": ("return", "返回", "返程"),
        "speed policy": ("speed", "速度", "快", "慢"),
        "execution confirmation": ("confirm", "确认", "执行前"),
    }
    covered = [
        name for name, tokens in dimensions.items() if any(token in rendered for token in tokens)
    ]
    missing = [name for name in dimensions if name not in covered]
    return {
        "covered": covered,
        "missing": missing,
        "coverage_ratio": len(covered) / len(dimensions),
    }


def _tools(_environment: ToolEnvironment) -> list[ToolPlugin]:
    return [
        ToolPlugin(
            tool_id="general.constraint-coverage",
            version="1.0.0",
            authority="read",
            input_type=None,
            output_type=None,
            input_schema=INPUT_SCHEMA,
            output_schema=OUTPUT_SCHEMA,
            handler=_coverage,
        )
    ]


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="general.constraint-coverage",
            name="约束覆盖检查",
            version="1.0.0",
            description="检查任务是否明确了安全、返程、速度和执行确认等通用约束。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definition"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="general.constraint-coverage",
                    kind="evidence",
                    name="约束覆盖检查",
                    description="指出任务约束中已覆盖和仍缺少的维度。",
                    input_schema=INPUT_SCHEMA,
                    output_schema=OUTPUT_SCHEMA,
                )
            ],
            permissions=["mission.read"],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="general",
                category_label="通用增强",
                slot_id="general.mission-advisors",
                slot_label="任务顾问",
                activation_mode="multiple",
                scope="general",
                category_order=0,
                slot_order=10,
                plugin_order=20,
            ),
        ),
        tool_factory=_tools,
    )
