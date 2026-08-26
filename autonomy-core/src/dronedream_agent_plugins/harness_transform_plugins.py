from __future__ import annotations

import math
from typing import Any

from dronedream_agent_core.contracts import (
    IntentArtifact,
    Px4Track,
    SemanticPlan,
    TaskGraph,
)
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _language_features(*, value: dict[str, object], **_: Any) -> dict[str, object]:
    message = str(value.get("message", ""))
    chinese_count = sum("\u4e00" <= character <= "\u9fff" for character in message)
    latin_count = sum(character.isascii() and character.isalpha() for character in message)
    dominant = "zh" if chinese_count >= latin_count else "en"
    return {
        **value,
        "language_features": {
            "dominant_language": dominant,
            "chinese_character_count": chinese_count,
            "latin_character_count": latin_count,
        },
    }


def _directive_features(*, value: dict[str, object], **_: Any) -> dict[str, object]:
    message = str(value.get("message", "")).casefold()
    groups = {
        "urgency": ("尽快", "马上", "立即", "紧急", "asap", "immediately"),
        "speed_change": ("快点", "慢点", "加速", "减速", "faster", "slower"),
        "payload": ("外卖", "包裹", "取件", "拿回", "pickup", "parcel", "delivery"),
        "inspection": ("检查", "巡检", "拍摄", "inspect", "survey", "photograph"),
        "privacy": ("隐私", "不要拍", "安静", "privacy", "do not record", "quiet"),
    }
    detected = [
        name for name, tokens in groups.items() if any(token in message for token in tokens)
    ]
    return {**value, "directive_classes": detected}


def _canonicalize_intent(*, value: IntentArtifact, **_: Any) -> IntentArtifact:
    constraints: list[str] = []
    seen: set[str] = set()
    for item in value.constraints:
        normalized = " ".join(item.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            constraints.append(normalized)
    return value.model_copy(update={"constraints": constraints})


def _normalize_entities(*, value: IntentArtifact, **_: Any) -> IntentArtifact:
    return value.model_copy(
        update={
            "start_entity": " ".join(value.start_entity.split()),
            "target_entity": " ".join(value.target_entity.split()),
            "return_entity": " ".join(value.return_entity.split()),
        }
    )


_ACTION_EVIDENCE = {
    "takeoff": "vehicle airborne state confirmed",
    "traverse": "target node pose reached within tolerance",
    "navigate": "target node pose reached within tolerance",
    "return": "return node pose reached within tolerance",
    "pickup": "payload attachment and custody state confirmed",
    "land": "on-ground state confirmed",
    "inspect": "inspection observation bound to target node",
}


def _enrich_task_evidence(*, value: TaskGraph, **_: Any) -> TaskGraph:
    nodes = []
    for node in value.nodes:
        evidence = list(dict.fromkeys(" ".join(item.split()) for item in node.success_evidence))
        required = _ACTION_EVIDENCE.get(node.action)
        if required and required not in evidence and len(evidence) < 16:
            evidence.append(required)
        nodes.append(node.model_copy(update={"success_evidence": evidence}))
    return value.model_copy(update={"nodes": nodes})


def _apply_retry_budget(
    *, value: TaskGraph, configuration: dict[str, object] | None = None, **_: Any
) -> TaskGraph:
    configured = configuration or {}
    movement_retries = int(configured.get("movement_retries", 2))
    interaction_retries = int(configured.get("interaction_retries", 1))
    nodes = []
    for node in value.nodes:
        budget = (
            movement_retries
            if node.action in {"traverse", "navigate", "return"}
            else interaction_retries
        )
        nodes.append(node.model_copy(update={"max_retries": max(node.max_retries, budget)}))
    return value.model_copy(update={"nodes": nodes})


def _deduplicate_targets(*, value: SemanticPlan, **_: Any) -> SemanticPlan:
    targets: list[str] = []
    for target in value.ordered_targets:
        if not targets or targets[-1] != target:
            targets.append(target)
    return value.model_copy(update={"ordered_targets": targets})


def _phase_speed_envelope(
    *, value: Px4Track, configuration: dict[str, object] | None = None, **_: Any
) -> Px4Track:
    configured = configuration or {}
    default_caps = {
        "launch": 1.0,
        "transit": 2.0,
        "stairs": 0.8,
        "pickup": 0.5,
        "return": 2.0,
        "land": 0.5,
    }
    raw_caps = configured.get("phase_speed_caps_mps", {})
    caps = {
        **default_caps,
        **(
            {str(key): float(item) for key, item in raw_caps.items()}
            if isinstance(raw_caps, dict)
            else {}
        ),
    }
    points = [
        point.model_copy(update={"speed_limit_mps": min(point.speed_limit_mps, caps[point.phase])})
        for point in value.points
    ]
    return value.model_copy(update={"points": points})


def _corner_speed_envelope(
    *, value: Px4Track, configuration: dict[str, object] | None = None, **_: Any
) -> Px4Track:
    configured = configuration or {}
    threshold_deg = float(configured.get("minimum_turn_angle_deg", 35.0))
    corner_speed_mps = float(configured.get("corner_speed_limit_mps", 0.8))
    points = list(value.points)
    for index in range(1, len(points) - 1):
        previous, current, following = points[index - 1], points[index], points[index + 1]
        incoming = (current.x - previous.x, current.y - previous.y, current.z - previous.z)
        outgoing = (following.x - current.x, following.y - current.y, following.z - current.z)
        incoming_norm = math.sqrt(sum(component * component for component in incoming))
        outgoing_norm = math.sqrt(sum(component * component for component in outgoing))
        if incoming_norm <= 1e-9 or outgoing_norm <= 1e-9:
            continue
        cosine = sum(a * b for a, b in zip(incoming, outgoing, strict=True)) / (
            incoming_norm * outgoing_norm
        )
        turn_angle_deg = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
        if turn_angle_deg >= threshold_deg:
            points[index] = current.model_copy(
                update={"speed_limit_mps": min(current.speed_limit_mps, corner_speed_mps)}
            )
    return value.model_copy(update={"points": points})


def _fuse_tool_advice(*, value: list[dict[str, object]], **_: Any) -> list[dict[str, object]]:
    by_tool: dict[str, dict[str, object]] = {}
    for index, item in enumerate(value):
        tool_id = str(item.get("tool_id") or f"anonymous-{index:04d}")
        previous = by_tool.get(tool_id)
        if previous is None or (not bool(previous.get("accepted")) and bool(item.get("accepted"))):
            by_tool[tool_id] = item
    return sorted(
        by_tool.values(),
        key=lambda item: (not bool(item.get("accepted")), str(item.get("tool_id", ""))),
    )


def plugin_definitions() -> list[PluginDefinition]:
    definitions: list[PluginDefinition] = []
    request_plugins = [
        (
            "input.language-features",
            "语言特征提取",
            "从原始自然语言中提取中英文字符分布，不改变用户原文。",
            _language_features,
        ),
        (
            "input.directive-features",
            "任务指令特征",
            "提取紧急、速度、载荷、巡检和隐私类明确指令。",
            _directive_features,
        ),
    ]
    for index, (plugin_id, name, description, handler) in enumerate(request_plugins, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.extract",
                capability_kind="structured-decoder",
                capability_name=name,
                capability_description=description,
                category_id="input",
                category_label="输入与结构化",
                slot_id="input.request-features",
                slot_label="请求特征管线",
                activation_mode="pipeline",
                category_order=10,
                slot_order=10,
                plugin_order=index * 10,
                pipeline_order=index * 10,
                hooks={"enrich_request": handler},
                default_enabled=True,
                failure_mode="isolate",
            )
        )
    intent_plugins = [
        (
            "input.intent-constraint-normalizer",
            "约束规范化",
            "清理并去重结构化意图中的约束，同时保留首次出现顺序。",
            _canonicalize_intent,
        ),
        (
            "input.intent-entity-normalizer",
            "实体规范化",
            "清理起点、目标和返程实体中的重复空白。",
            _normalize_entities,
        ),
    ]
    for index, (plugin_id, name, description, handler) in enumerate(intent_plugins, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.normalize",
                capability_kind="structured-decoder",
                capability_name=name,
                capability_description=description,
                category_id="input",
                category_label="输入与结构化",
                slot_id="input.intent-normalizers",
                slot_label="意图规范化管线",
                activation_mode="pipeline",
                category_order=10,
                slot_order=20,
                plugin_order=index * 10,
                pipeline_order=index * 10,
                hooks={"normalize_intent": handler},
                default_enabled=True,
                failure_mode="fail-closed",
            )
        )
    task_plugins = [
        (
            "planning.task-evidence-enricher",
            "任务证据增强",
            "为每类任务补充可检查的成功证据，不替换模型已有证据。",
            _enrich_task_evidence,
            {},
        ),
        (
            "planning.task-retry-budget",
            "任务重试预算",
            "按移动和交互任务配置最小重试预算。",
            _apply_retry_budget,
            {
                "type": "object",
                "properties": {
                    "movement_retries": {"type": "integer", "minimum": 0, "maximum": 8},
                    "interaction_retries": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 8,
                    },
                },
                "additionalProperties": False,
            },
        ),
    ]
    for index, (plugin_id, name, description, handler, schema) in enumerate(task_plugins, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.transform",
                capability_kind="task-decomposer",
                capability_name=name,
                capability_description=description,
                category_id="planning",
                category_label="任务规划",
                slot_id="planning.task-transformers",
                slot_label="任务图增强管线",
                activation_mode="pipeline",
                category_order=40,
                slot_order=10,
                plugin_order=index * 10,
                pipeline_order=index * 10,
                hooks={"transform_task_graph": handler},
                default_enabled=True,
                failure_mode="fail-closed",
                configuration_schema=schema,
            )
        )
    definitions.append(
        hook_plugin(
            module_name=__name__,
            plugin_id="planning.semantic-target-deduplicator",
            name="语义目标去重",
            description="删除连续重复目标，减少无意义的零长度路线段。",
            capability_id="planning.semantic-target-deduplicator.optimize",
            capability_kind="plan-optimizer",
            capability_name="语义目标去重",
            capability_description="删除连续重复目标，减少无意义的零长度路线段。",
            category_id="planning",
            category_label="任务规划",
            slot_id="planning.semantic-optimizers",
            slot_label="语义计划优化管线",
            activation_mode="pipeline",
            category_order=40,
            slot_order=20,
            plugin_order=10,
            pipeline_order=10,
            hooks={"optimize_semantic_plan": _deduplicate_targets},
            default_enabled=True,
            failure_mode="fail-closed",
        )
    )
    definitions.append(
        hook_plugin(
            module_name=__name__,
            plugin_id="planning.corner-speed-envelope",
            name="转弯速度包线",
            description="识别三维航迹急转点并限制转弯速度，避免按直线速度穿越门洞和拐角。",
            capability_id="planning.corner-speed-envelope.optimize",
            capability_kind="plan-optimizer",
            capability_name="转弯速度包线",
            capability_description="按三维转角限制局部航迹速度。",
            category_id="planning",
            category_label="任务规划",
            slot_id="planning.track-optimizers",
            slot_label="航迹优化管线",
            activation_mode="pipeline",
            category_order=40,
            slot_order=40,
            plugin_order=20,
            pipeline_order=20,
            runs_after=["planning.phase-speed-envelope"],
            hooks={"optimize_track": _corner_speed_envelope},
            default_enabled=False,
            failure_mode="fail-closed",
            configuration_schema={
                "type": "object",
                "properties": {
                    "minimum_turn_angle_deg": {
                        "type": "number",
                        "minimum": 5,
                        "maximum": 175,
                    },
                    "corner_speed_limit_mps": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 5,
                    },
                },
                "additionalProperties": False,
            },
        )
    )
    definitions.append(
        hook_plugin(
            module_name=__name__,
            plugin_id="planning.phase-speed-envelope",
            name="分阶段速度包线",
            description="按起飞、通行、楼梯、取件、返程和降落阶段限制航迹速度。",
            capability_id="planning.phase-speed-envelope.optimize",
            capability_kind="plan-optimizer",
            capability_name="分阶段速度包线",
            capability_description="按飞行阶段限制航迹速度。",
            category_id="planning",
            category_label="任务规划",
            slot_id="planning.track-optimizers",
            slot_label="航迹优化管线",
            activation_mode="pipeline",
            category_order=40,
            slot_order=40,
            plugin_order=10,
            pipeline_order=10,
            hooks={"optimize_track": _phase_speed_envelope},
            default_enabled=True,
            failure_mode="fail-closed",
            configuration_schema={
                "type": "object",
                "properties": {
                    "phase_speed_caps_mps": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "maximum": 20,
                        },
                    }
                },
                "additionalProperties": False,
            },
        )
    )
    definitions.append(
        hook_plugin(
            module_name=__name__,
            plugin_id="tools.result-fusion-deduplicator",
            name="工具结果融合",
            description="按工具身份去重建议并优先保留已验收结果。",
            capability_id="tools.result-fusion-deduplicator.fuse",
            capability_kind="result-fusion",
            capability_name="工具结果融合",
            capability_description="去重并稳定排序工具建议。",
            category_id="tools",
            category_label="工具与服务",
            slot_id="tools.result-fusion",
            slot_label="工具结果融合管线",
            activation_mode="pipeline",
            category_order=50,
            slot_order=40,
            plugin_order=10,
            pipeline_order=10,
            hooks={"fuse_results": _fuse_tool_advice},
            default_enabled=True,
            failure_mode="isolate",
        )
    )
    return definitions
