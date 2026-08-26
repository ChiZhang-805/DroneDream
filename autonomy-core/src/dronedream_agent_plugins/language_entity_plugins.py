from __future__ import annotations

import re
from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _zh_locale(*, value: dict[str, object], request: Any, **_: Any) -> dict[str, object]:
    if request.locale != "zh-CN":
        return value
    dialect_terms = {
        "保安室": "security booth",
        "门卫室": "security booth",
        "外卖柜": "delivery locker",
        "取餐点": "pickup point",
    }
    normalized = request.message
    for source, target in dialect_terms.items():
        normalized = normalized.replace(source, target)
    return {**value, "locale": "zh-CN", "normalized_message": normalized}


def _en_locale(*, value: dict[str, object], request: Any, **_: Any) -> dict[str, object]:
    if request.locale != "en-US":
        return value
    return {**value, "locale": "en-US", "normalized_message": request.message}


def _map_entity_resolver(
    *, value: dict[str, object], request: Any, map_catalog: Any, **_: Any
) -> dict[str, object]:
    message = str(value.get("normalized_message") or request.message).casefold()
    matches: list[dict[str, object]] = []
    for entity in map_catalog.entities:
        names = [entity.entity_id, *entity.aliases]
        for name in names:
            if re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", message):
                matches.append(
                    {"entity_id": entity.entity_id, "matched_alias": name, "confidence": 1.0}
                )
                break
    return {**value, "resolved_entities": matches}


def plugin_definitions() -> list[PluginDefinition]:
    values = [
        (
            "input.locale-zh-cn",
            "简体中文与常用别名",
            "规范中文口语、地点俗称和任务表达。",
            "locale-policy",
            "resolve_locale",
            _zh_locale,
            10,
        ),
        (
            "input.locale-en-us",
            "English (US)",
            "Normalize English mission language without translating identifiers.",
            "locale-policy",
            "resolve_locale",
            _en_locale,
            20,
        ),
        (
            "input.entity-map-ontology",
            "地图实体解析",
            "依据已冻结地图本体和别名解析地点实体。",
            "entity-resolver",
            "resolve_entity",
            _map_entity_resolver,
            30,
        ),
    ]
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.{hook}",
            capability_kind=kind,
            capability_name=name,
            capability_description=description,
            category_id="input",
            category_label="输入与理解",
            slot_id=(
                "input.locale-pipeline" if kind == "locale-policy" else "input.entity-pipeline"
            ),
            slot_label=("语言与方言" if kind == "locale-policy" else "实体解析"),
            activation_mode="pipeline",
            category_order=10,
            slot_order=(20 if kind == "locale-policy" else 30),
            plugin_order=order,
            pipeline_order=order,
            hooks={hook: handler},
            default_enabled=True,
            failure_mode="isolate",
        )
        for plugin_id, name, description, kind, hook, handler, order in values
    ]
