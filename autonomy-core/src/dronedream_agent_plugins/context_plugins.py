from __future__ import annotations

from typing import Any

from dronedream_agent_core.contracts import ConversationWindow, MapAsset, MapCatalog, MissionRequest
from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _structured_window(*, window: ConversationWindow) -> dict[str, object]:
    recent: list[dict[str, object]] = []
    for event in window.recent_events:
        payload = event.payload
        if event.role == "tool":
            payload = {
                key: payload.get(key)
                for key in (
                    "tool_id",
                    "outcome",
                    "input_sha256",
                    "output_sha256",
                    "issue_codes",
                )
            }
        recent.append(
            {
                "sequence": event.sequence,
                "role": event.role,
                "event_type": event.event_type,
                "payload": payload,
            }
        )
    return {
        "strategy": "structured-window",
        "conversation_id": window.conversation_id,
        "summary": window.summary,
        "recent_events": recent,
    }


def _event_ledger(*, window: ConversationWindow) -> dict[str, object]:
    return {
        "strategy": "event-ledger",
        "conversation_id": window.conversation_id,
        "summary": window.summary,
        "events": [
            {
                "sequence": event.sequence,
                "role": event.role,
                "event_type": event.event_type,
                "artifact_sha256": sha256_json(event.payload),
            }
            for event in window.recent_events
        ],
    }


def _map_context(
    *, value: dict[str, object], map_catalog: MapCatalog, map_graph: MapAsset, **_: Any
) -> dict[str, object]:
    return {
        **value,
        "map_context": {
            "asset_id": map_graph.asset_id,
            "node_count": len(map_graph.nodes),
            "edge_count": len(map_graph.edges),
            "entities": [
                {"entity_id": item.entity_id, "aliases": item.aliases}
                for item in map_catalog.entities
            ],
        },
    }


def _request_context(
    *, value: dict[str, object], request: MissionRequest, **_: Any
) -> dict[str, object]:
    memory_policy = request.input_metadata.get("memory_policy")
    return {
        **value,
        "request_context": {
            "conversation_id": request.conversation_id,
            "locale": request.locale,
            "start_entity": request.start_entity,
            "message_length": len(request.message),
            "memory_policy": memory_policy if isinstance(memory_policy, dict) else {},
        },
    }


def _safety_context(*, value: dict[str, object], **_: Any) -> dict[str, object]:
    return {
        **value,
        "non_relaxable_context": {
            "model_has_actuator_authority": False,
            "unknown_critical_state": "hold-or-abort",
            "runtime_change_requires_safe_hold": True,
        },
    }


def _sqlite_wal_store(**_: Any) -> dict[str, object]:
    return {
        "backend": "sqlite-wal",
        "durable": True,
        "provider_context_is_not_memory": True,
    }


def _balanced_retrieval(**_: Any) -> dict[str, object]:
    return {"maximum_recent_events": 24, "include_summary": True}


def _audit_retrieval(**_: Any) -> dict[str, object]:
    return {"maximum_recent_events": 120, "include_summary": True}


def _extractive_summary(*, window: ConversationWindow, **_: Any) -> dict[str, object]:
    statements: list[str] = []
    for event in window.recent_events:
        if event.event_type == "mission.request":
            message = event.payload.get("message")
            if isinstance(message, str) and message.strip():
                statements.append(f"User request: {message.strip()[:500]}")
        elif event.event_type.startswith("model.intent_parser"):
            artifact = event.payload.get("artifact")
            if isinstance(artifact, dict):
                goal = artifact.get("goal")
                if isinstance(goal, str):
                    statements.append(f"Resolved goal: {goal[:500]}")
    through = max((event.sequence for event in window.recent_events), default=0)
    return {
        "summary": "\n".join(dict.fromkeys(statements[-12:])),
        "through_sequence": through,
    }


def _standard_retention(**_: Any) -> dict[str, object]:
    return {"maximum_events": 10_000, "policy": "bounded-event-ledger"}


def _minimal_retention(**_: Any) -> dict[str, object]:
    return {"maximum_events": 500, "policy": "privacy-minimal"}


def plugin_definitions() -> list[PluginDefinition]:
    strategies = [
        (
            "context.structured-window",
            "结构化上下文窗口",
            "保留近期事件并压缩大型工具结果，适合日常任务对话。",
            _structured_window,
            True,
        ),
        (
            "context.event-ledger",
            "事件账本上下文",
            "以有序事件和哈希摘要组织上下文，适合审计与长任务。",
            _event_ledger,
            False,
        ),
    ]
    enrichers = [
        (
            "context.map-ontology",
            "地图本体上下文",
            "加入地图实体、别名、节点和边界规模。",
            _map_context,
            10,
        ),
        (
            "context.request-identity",
            "任务身份上下文",
            "加入稳定对话 ID、语言、起点和本轮消息信息。",
            _request_context,
            20,
        ),
        (
            "context.safety-boundary",
            "安全边界上下文",
            "在每次意图提取前加入不可放宽的执行权限边界。",
            _safety_context,
            30,
        ),
    ]
    definitions = [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.compact",
            capability_kind="context-strategy",
            capability_name=name,
            capability_description=description,
            category_id="context",
            category_label="上下文与记忆",
            slot_id="context.compaction-strategy",
            slot_label="上下文策略",
            activation_mode="single",
            category_order=30,
            slot_order=10,
            plugin_order=index * 10,
            hooks={"compact_context": handler},
            default_enabled=enabled,
            failure_mode="fail-closed",
        )
        for index, (plugin_id, name, description, handler, enabled) in enumerate(
            strategies, start=1
        )
    ]
    definitions.extend(
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.enrich",
            capability_kind="context-enricher",
            capability_name=name,
            capability_description=description,
            category_id="context",
            category_label="上下文与记忆",
            slot_id="context.enrichment",
            slot_label="上下文增强管线",
            activation_mode="pipeline",
            category_order=30,
            slot_order=20,
            plugin_order=order,
            pipeline_order=order,
            hooks={"enrich_context": handler},
            default_enabled=True,
            failure_mode="isolate",
        )
        for plugin_id, name, description, handler, order in enrichers
    )
    for plugin_id, name, description, slot_id, slot_label, kind, hook, handler, enabled, order in [
        (
            "context.store-sqlite-wal",
            "SQLite WAL 上下文库",
            "使用事务化事件账本、摘要和供应商上下文指针。",
            "context.store",
            "上下文存储",
            "context-store",
            "resolve_context_store",
            _sqlite_wal_store,
            True,
            10,
        ),
        (
            "context.retrieve-balanced",
            "平衡检索",
            "读取摘要和最近二十四条结构化事件。",
            "context.retrieval-policy",
            "上下文检索",
            "context-retriever",
            "retrieve_context",
            _balanced_retrieval,
            True,
            10,
        ),
        (
            "context.retrieve-audit",
            "审计检索",
            "为评估任务读取更长的结构化事件窗口。",
            "context.retrieval-policy",
            "上下文检索",
            "context-retriever",
            "retrieve_context",
            _audit_retrieval,
            False,
            20,
        ),
        (
            "context.summary-extractive",
            "结构化摘要",
            "从真实任务请求和意图产物提取无幻觉摘要。",
            "context.summarization-policy",
            "上下文摘要",
            "context-summarizer",
            "summarize_context",
            _extractive_summary,
            True,
            10,
        ),
        (
            "context.retention-standard",
            "标准留存",
            "每个任务保留一万条事件并持续保留摘要。",
            "context.retention-policy",
            "上下文留存",
            "retention-policy",
            "resolve_retention",
            _standard_retention,
            True,
            10,
        ),
        (
            "context.retention-minimal",
            "最小留存",
            "每个任务只保留五百条事件，适合隐私敏感部署。",
            "context.retention-policy",
            "上下文留存",
            "retention-policy",
            "resolve_retention",
            _minimal_retention,
            False,
            20,
        ),
    ]:
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.{hook}",
                capability_kind=kind,
                capability_name=name,
                capability_description=description,
                category_id="context",
                category_label="上下文与记忆",
                slot_id=slot_id,
                slot_label=slot_label,
                activation_mode="single",
                category_order=30,
                slot_order=order + 30,
                plugin_order=order,
                hooks={hook: handler},
                default_enabled=enabled,
                failure_mode="fail-closed",
                permissions=["context.read", "context.write-summary"],
            )
        )
    return definitions
