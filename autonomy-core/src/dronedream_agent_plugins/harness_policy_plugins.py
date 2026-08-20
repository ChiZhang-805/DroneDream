from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _constant(payload: dict[str, object]):
    def resolve(**_: Any) -> dict[str, object]:
        return dict(payload)

    return resolve


def _event_bus(*, event: str, payload: dict[str, object], **_: Any) -> dict[str, object]:
    return {
        "accepted": True,
        "transport": "in-process",
        "event": event,
        "payload": payload,
    }


def _observer(*, event: str, payload: dict[str, object], **_: Any) -> dict[str, object]:
    return {
        "observer": "execution-ledger",
        "event": event,
        "payload_sha256_required": True,
        "accepted": bool(payload),
    }


def _policy(
    *,
    plugin_id: str,
    name: str,
    description: str,
    kind: str,
    slot_id: str,
    slot_label: str,
    hook_name: str,
    payload: dict[str, object],
    order: int,
    enabled: bool,
) -> PluginDefinition:
    return hook_plugin(
        module_name=__name__,
        plugin_id=plugin_id,
        name=name,
        description=description,
        capability_id=f"{plugin_id}.resolve",
        capability_kind=kind,
        capability_name=name,
        capability_description=description,
        category_id="harness",
        category_label="Harness 与智能体",
        slot_id=slot_id,
        slot_label=slot_label,
        activation_mode="single",
        category_order=10,
        slot_order=order,
        plugin_order=order,
        hooks={hook_name: _constant(payload)},
        default_enabled=enabled,
        failure_mode="fail-closed",
        swap_policy="next-mission",
        metadata=payload,
    )


def plugin_definitions() -> list[PluginDefinition]:
    definitions = [
        _policy(
            plugin_id="harness.scheduler-parallel-ready",
            name="就绪节点并行调度",
            description="并行运行依赖已满足的独立节点，核心安全门仍保持顺序。",
            kind="harness-scheduler",
            slot_id="harness.scheduler",
            slot_label="Harness 调度器",
            hook_name="resolve_schedule",
            payload={"strategy": "parallel-ready", "maximum_parallelism": 4},
            order=30,
            enabled=True,
        ),
        _policy(
            plugin_id="harness.scheduler-sequential",
            name="完全顺序调度",
            description="适用于调试与严格复现，每次只运行一个 Harness 节点。",
            kind="harness-scheduler",
            slot_id="harness.scheduler",
            slot_label="Harness 调度器",
            hook_name="resolve_schedule",
            payload={"strategy": "sequential", "maximum_parallelism": 1},
            order=31,
            enabled=False,
        ),
        _policy(
            plugin_id="harness.retry-bounded-exponential",
            name="有界指数重试",
            description="仅对可恢复故障执行有界重试，并记录每一次尝试。",
            kind="retry-policy",
            slot_id="harness.retry-policy",
            slot_label="重试策略",
            hook_name="resolve_retry",
            payload={
                "maximum_retries": 24,
                "provider_attempts": 3,
                "backoff": "exponential",
                "jitter": True,
            },
            order=40,
            enabled=True,
        ),
        _policy(
            plugin_id="harness.retry-immediate-once",
            name="快速单次重试",
            description="低延迟任务只进行一次立即重试。",
            kind="retry-policy",
            slot_id="harness.retry-policy",
            slot_label="重试策略",
            hook_name="resolve_retry",
            payload={
                "maximum_retries": 1,
                "provider_attempts": 2,
                "backoff": "none",
                "jitter": False,
            },
            order=41,
            enabled=False,
        ),
        _policy(
            plugin_id="harness.timeout-adaptive",
            name="阶段自适应超时",
            description="为模型、工具和本地验证分别设置边界明确的超时时间。",
            kind="timeout-policy",
            slot_id="harness.timeout-policy",
            slot_label="超时策略",
            hook_name="resolve_timeout",
            payload={
                "model_seconds": 180.0,
                "tool_seconds": 60.0,
                "local_stage_seconds": 30.0,
                "mission_seconds": 900.0,
            },
            order=50,
            enabled=True,
        ),
        _policy(
            plugin_id="harness.timeout-low-latency",
            name="低延迟超时",
            description="面向应急预览缩短模型和工具等待时间，超时后进入安全回退。",
            kind="timeout-policy",
            slot_id="harness.timeout-policy",
            slot_label="超时策略",
            hook_name="resolve_timeout",
            payload={
                "model_seconds": 45.0,
                "tool_seconds": 20.0,
                "local_stage_seconds": 10.0,
                "mission_seconds": 300.0,
            },
            order=51,
            enabled=False,
        ),
        _policy(
            plugin_id="harness.budget-balanced",
            name="均衡调用预算",
            description="限制模型、工具、节点、重试和并行度，避免无限循环。",
            kind="budget-policy",
            slot_id="harness.budget-policy",
            slot_label="调用预算",
            hook_name="resolve_budget",
            payload={
                "maximum_model_calls": 48,
                "maximum_tool_calls": 16,
                "maximum_nodes": 128,
                "maximum_retries": 24,
                "maximum_parallelism": 4,
            },
            order=60,
            enabled=True,
        ),
        _policy(
            plugin_id="harness.budget-cost-capped",
            name="费用封顶预算",
            description="减少模型审查和顾问工具调用，同时保留所有安全门。",
            kind="budget-policy",
            slot_id="harness.budget-policy",
            slot_label="调用预算",
            hook_name="resolve_budget",
            payload={
                "maximum_model_calls": 16,
                "maximum_tool_calls": 4,
                "maximum_nodes": 96,
                "maximum_retries": 8,
                "maximum_parallelism": 2,
            },
            order=61,
            enabled=False,
        ),
        _policy(
            plugin_id="harness.fallback-safe-degrade",
            name="安全降级回退",
            description="可选顾问失败时隔离，模型或安全节点失败时悬停并停止准备。",
            kind="fallback-policy",
            slot_id="harness.fallback-policy",
            slot_label="回退策略",
            hook_name="resolve_fallback",
            payload={
                "optional_failure": "isolate",
                "planning_failure": "stop",
                "runtime_failure": "safe-hold",
                "may_bypass_core_gate": False,
            },
            order=70,
            enabled=True,
        ),
        _policy(
            plugin_id="harness.cache-mission-hash",
            name="任务哈希缓存",
            description="只复用输入、插件快照和资产哈希完全一致的只读结果。",
            kind="cache-policy",
            slot_id="harness.cache-policy",
            slot_label="缓存策略",
            hook_name="resolve_cache",
            payload={
                "strategy": "mission-hash",
                "cache_read_only": True,
                "cache_model_outputs": False,
                "cache_safety_authorization": False,
            },
            order=80,
            enabled=True,
        ),
    ]
    definitions.extend(
        [
            hook_plugin(
                module_name=__name__,
                plugin_id="harness.event-bus-in-process",
                name="进程内任务事件总线",
                description="在任务准备链中传递哈希绑定事件，不跨越进程权限边界。",
                capability_id="harness.event-bus-in-process.transport",
                capability_kind="event-bus",
                capability_name="进程内事件传输",
                capability_description="传输结构化 Harness 生命周期事件。",
                category_id="harness",
                category_label="Harness 与智能体",
                slot_id="harness.event-bus",
                slot_label="事件总线",
                activation_mode="single",
                category_order=10,
                slot_order=90,
                plugin_order=10,
                hooks={"transport_message": _event_bus},
                default_enabled=True,
                failure_mode="fail-closed",
                swap_policy="next-mission",
            ),
            hook_plugin(
                module_name=__name__,
                plugin_id="harness.observer-execution-ledger",
                name="Harness 执行账本",
                description="记录拓扑、阶段与策略事件，用于回放和审计。",
                capability_id="harness.observer-execution-ledger.observe",
                capability_kind="observer",
                capability_name="执行账本观测器",
                capability_description="为 Harness 事件生成可审计观测记录。",
                category_id="harness",
                category_label="Harness 与智能体",
                slot_id="harness.observers",
                slot_label="Harness 观测器",
                activation_mode="multiple",
                category_order=10,
                slot_order=100,
                plugin_order=10,
                hooks={"observe_harness": _observer},
                default_enabled=True,
                failure_mode="isolate",
                swap_policy="anytime",
            ),
        ]
    )
    return definitions
