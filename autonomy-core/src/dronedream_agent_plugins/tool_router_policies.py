from __future__ import annotations

from typing import Any

from dronedream_agent_core.contracts import MissionContract
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _hybrid(*, recommended_tool_ids: list[str], **_: Any) -> dict[str, object]:
    return {
        "strategy": "rules-plus-model",
        "recommended_tool_ids": recommended_tool_ids,
    }


def _model_only(**_: Any) -> dict[str, object]:
    return {"strategy": "model", "recommended_tool_ids": []}


def _safety_first(
    *,
    contract: MissionContract,
    catalog: list[dict[str, object]],
    recommended_tool_ids: list[str],
    **_: Any,
) -> dict[str, object]:
    values = set(recommended_tool_ids)
    for item in catalog:
        metadata = item.get("routing_metadata")
        if not isinstance(metadata, dict):
            continue
        domains = metadata.get("domains", [])
        if isinstance(domains, list) and set(domains).intersection(
            {"safety", "energy", "communications", "landing"}
        ):
            values.add(str(item["tool_id"]))
    return {
        "strategy": "safety-first-hybrid",
        "recommended_tool_ids": sorted(values),
        "contract_id": contract.contract_id,
    }


def plugin_definitions() -> list[PluginDefinition]:
    values = [
        (
            "tools.router-hybrid",
            "混合工具路由",
            "由确定性推荐条件提供底线，再由模型补充任务相关工具。",
            _hybrid,
            True,
        ),
        (
            "tools.router-model",
            "模型工具路由",
            "让模型完全根据结构化工具目录选择可选工具。",
            _model_only,
            False,
        ),
        (
            "tools.router-safety-first",
            "安全优先工具路由",
            "自动推荐安全、能源、通信和紧急降落相关工具，再交给模型补充。",
            _safety_first,
            False,
        ),
    ]
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.recommend",
            capability_kind="tool-router",
            capability_name=name,
            capability_description=description,
            category_id="tools",
            category_label="工具与集成",
            slot_id="tools.router-policy",
            slot_label="工具路由策略",
            activation_mode="single",
            category_order=50,
            slot_order=10,
            plugin_order=index * 10,
            hooks={"recommend_tools": handler},
            default_enabled=enabled,
            failure_mode="fail-closed",
        )
        for index, (plugin_id, name, description, handler, enabled) in enumerate(values, start=1)
    ]
