from __future__ import annotations

from typing import Any

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
    "required": ["goal", "payload_action", "constraints"],
    "properties": {
        "goal": {"type": "string", "minLength": 1},
        "payload_action": {"type": "string"},
        "constraints": {"type": "array", "items": {"type": "string"}},
    },
}
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["risk_level", "risk_factors", "recommended_focus"],
    "properties": {
        "risk_level": {"type": "string", "enum": ["normal", "elevated", "high"]},
        "risk_factors": {"type": "array", "items": {"type": "string"}},
        "recommended_focus": {"type": "array", "items": {"type": "string"}},
    },
}


def _profile(value: dict[str, object]) -> dict[str, Any]:
    constraints = [str(item).lower() for item in value.get("constraints", [])]
    factors: list[str] = []
    focus = ["telemetry continuity", "abort availability"]
    if value.get("payload_action") not in {None, "none"}:
        factors.append("payload interaction")
        focus.extend(["payload identity", "mass and retention confirmation"])
    if any(token in " ".join(constraints) for token in ("indoor", "室内", "楼", "door")):
        factors.append("constrained indoor geometry")
        focus.append("continuous vehicle-envelope clearance")
    if any(token in " ".join(constraints) for token in ("fast", "快速", "尽快")):
        factors.append("time pressure")
        focus.append("speed must remain subordinate to safety margins")
    level = "high" if len(factors) >= 2 else "elevated" if factors else "normal"
    return {"risk_level": level, "risk_factors": factors, "recommended_focus": focus}


def _tools(_environment: ToolEnvironment) -> list[ToolPlugin]:
    return [
        ToolPlugin(
            tool_id="general.mission-risk-profile",
            version="1.0.0",
            authority="read",
            input_type=None,
            output_type=None,
            input_schema=INPUT_SCHEMA,
            output_schema=OUTPUT_SCHEMA,
            handler=_profile,
        )
    ]


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="general.mission-risk-profile",
            name="任务风险画像",
            version="1.0.0",
            description="从任务目标、载荷动作和约束中补充结构化风险关注点。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definition"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="general.mission-risk-profile",
                    kind="evidence",
                    name="任务风险画像",
                    description="生成不具有控制权的任务风险建议。",
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
                plugin_order=10,
            ),
        ),
        tool_factory=_tools,
    )
