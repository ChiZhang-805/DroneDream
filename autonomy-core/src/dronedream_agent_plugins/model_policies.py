from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin

CRITIC_ROLES = frozenset(
    {
        "intent_critic",
        "plan_critic",
        "execution_monitor",
        "completion_verifier",
    }
)

SAFETY_ROLES = frozenset(
    {
        "execution_monitor",
        "completion_verifier",
        "runtime_message_classifier",
        "runtime_amendment_validator",
    }
)

PERCEPTION_ROLES = frozenset(
    {
        "attachment_interpreter",
        "scene_interpreter",
        "target_verifier",
    }
)


def _specialist(*, role: str, requested_port: str, **_: Any) -> dict[str, str]:
    if role in SAFETY_ROLES:
        return {"port": "safety"}
    if role in PERCEPTION_ROLES:
        return {"port": "perception"}
    return {"port": "critic" if role in CRITIC_ROLES else "primary"}


def _unified(**_: Any) -> dict[str, str]:
    return {"port": "primary"}


def _adversarial(*, role: str, requested_port: str, **_: Any) -> dict[str, str]:
    review_role = role.endswith("critic") or role in {
        "execution_monitor",
        "completion_verifier",
        "runtime_message_classifier",
    }
    return {"port": "critic" if review_role else requested_port}


def plugin_definitions() -> list[PluginDefinition]:
    values = [
        (
            "models.role-specialist",
            "角色专用模型分配",
            "规划角色使用主模型，审查和验收角色使用独立 critic 端口。",
            _specialist,
            True,
        ),
        (
            "models.role-unified",
            "统一模型分配",
            "所有 Harness 角色使用同一个主模型，适合单一私有模型部署。",
            _unified,
            False,
        ),
        (
            "models.role-adversarial",
            "对抗式审查分配",
            "扩大 critic 端口覆盖范围，让运行消息和最终验收也由审查模型处理。",
            _adversarial,
            False,
        ),
    ]
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.select",
            capability_kind="model-policy",
            capability_name=name,
            capability_description=description,
            category_id="models",
            category_label="模型与推理",
            slot_id="models.role-policy",
            slot_label="模型角色分配",
            activation_mode="single",
            category_order=20,
            slot_order=20,
            plugin_order=index * 10,
            hooks={"select_port": handler},
            default_enabled=enabled,
            failure_mode="fail-closed",
        )
        for index, (plugin_id, name, description, handler, enabled) in enumerate(values, start=1)
    ]
