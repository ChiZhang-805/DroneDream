from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _append(fragment: str, *, roles: set[str] | None = None):
    def augment(*, value: str, role: str, **_: Any) -> str:
        if roles is not None and role not in roles:
            return value
        return f"{value.rstrip()}\n\nPLUGIN PROMPT PACK:\n{fragment.strip()}\n"

    return augment


def plugin_definitions() -> list[PluginDefinition]:
    values = [
        (
            "prompt.structured-discipline",
            "结构化输出纪律",
            "强调只填写目标 Schema、保留未知值并避免把推测写成事实。",
            "Return only the requested structured artifact. Preserve unknown values as unknown; "
            "never invent telemetry, map entities, tool results, permissions, or evidence.",
            None,
            True,
        ),
        (
            "prompt.campus-grounding",
            "校园地图落地",
            "要求所有位置、路线和任务动作绑定地图实体及节点。",
            "Ground every location in the supplied campus map catalog. Never create an entity, "
            "node, doorway, floor, road, pickup point, or landing site absent from that catalog.",
            {"intent_parser", "intent_critic", "task_decomposer", "global_planner", "plan_critic"},
            True,
        ),
        (
            "prompt.adversarial-review",
            "对抗式审查",
            "让 critic 主动寻找遗漏约束、错误假设和证据不足。",
            "Act as an independent adversarial reviewer. Search for omitted user constraints, "
            "identity confusion, stale-plan assumptions, unsafe side effects, and evidence gaps.",
            {"intent_critic", "plan_critic", "completion_verifier"},
            True,
        ),
        (
            "prompt.payload-custody",
            "载荷交接与保管",
            "强化取件身份、抓取确认、质量变化和返程载荷状态。",
            "For payload missions, keep pickup identity, pre-contact hold, attachment evidence, "
            "mass/inertia update, custody state, and return authorization as explicit steps.",
            {"intent_parser", "task_decomposer", "global_planner", "plan_critic"},
            False,
        ),
        (
            "prompt.operator-concise",
            "操作员简洁输出",
            "在不减少结构化字段的前提下压缩面向用户的解释。",
            "Keep human-facing summaries short and operational. Do not omit any required "
            "structured field, gate, issue code, repair instruction, or evidence reference.",
            None,
            False,
        ),
        (
            "prompt.runtime-stability",
            "运行期稳定优先",
            "在检查点和中途指令处理中优先稳定悬停、冻结副作用与证据绑定。",
            "During execution, treat stable hold, inhibited side effects, execution identity, "
            "telemetry freshness, deterministic gates, and replacement-track adoption evidence "
            "as mandatory. Never infer that motion may resume from model confidence alone.",
            {
                "execution_monitor",
                "runtime_message_classifier",
                "completion_verifier",
            },
            True,
        ),
    ]
    definitions: list[PluginDefinition] = []
    for index, (plugin_id, name, description, fragment, roles, enabled) in enumerate(
        values, start=1
    ):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.augment",
                capability_kind="prompt-pack",
                capability_name=name,
                capability_description=description,
                category_id="models",
                category_label="模型与推理",
                slot_id="models.prompt-packs",
                slot_label="Prompt 扩展管线",
                activation_mode="pipeline",
                category_order=20,
                slot_order=30,
                plugin_order=index * 10,
                pipeline_order=index * 10,
                hooks={"augment_prompt": _append(fragment, roles=roles)},
                default_enabled=enabled,
                failure_mode="isolate",
            )
        )
    return definitions
