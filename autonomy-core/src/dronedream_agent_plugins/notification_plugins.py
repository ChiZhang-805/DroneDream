from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _plan_ready(*, summary: dict[str, object], **_: Any) -> dict[str, object]:
    english = summary.get("locale") == "en-US"
    return {
        "channel": "task-timeline",
        "kind": "plan",
        "content": (
            f"Plan ready: {summary['goal']}" if english else f"计划已生成：{summary['goal']}"
        ),
        "metadata": {
            "contract_id": summary["contract_id"],
            "plan_revision_id": summary["plan_revision_id"],
            "plugin_snapshot_id": summary["plugin_snapshot_id"],
        },
    }


def _planning_metrics(*, summary: dict[str, object], **_: Any) -> dict[str, object]:
    english = summary.get("locale") == "en-US"
    return {
        "channel": "task-timeline",
        "kind": "status",
        "content": (
            f"Planning evidence: {summary['model_calls']} model calls, "
            f"minimum clearance {float(summary['minimum_clearance_m']):.2f} m"
            if english
            else f"规划证据：{summary['model_calls']} 次模型调用，"
            f"最小净空 {float(summary['minimum_clearance_m']):.2f} m"
        ),
        "metadata": {
            "planning_attempts": summary["planning_attempts"],
            "plugin_catalog_sha256": summary["plugin_catalog_sha256"],
        },
    }


def _operator_checklist(*, summary: dict[str, object], **_: Any) -> dict[str, object]:
    english = summary.get("locale") == "en-US"
    return {
        "channel": "task-timeline",
        "kind": "status",
        "content": (
            "Before execution, confirm the target, return location, map, drone, "
            "and mission contract."
            if english
            else "执行前请确认目标、返程位置、地图、无人机和任务合同。"
        ),
        "metadata": {
            "target_entity": summary["target_entity"],
            "return_entity": summary["return_entity"],
            "contract_id": summary["contract_id"],
        },
    }


def plugin_definitions() -> list[PluginDefinition]:
    values = [
        (
            "notification.plan-ready",
            "计划就绪通知",
            "在任务对话时间线中发布与合同和插件快照绑定的计划就绪消息。",
            _plan_ready,
            True,
        ),
        (
            "notification.planning-metrics",
            "规划指标通知",
            "在时间线中补充模型调用、规划轮次和最小净空摘要。",
            _planning_metrics,
            False,
        ),
        (
            "notification.operator-checklist",
            "执行前确认提醒",
            "在计划生成后加入执行前人工确认清单。",
            _operator_checklist,
            False,
        ),
    ]
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.render",
            capability_kind="notification",
            capability_name=name,
            capability_description=description,
            category_id="interaction",
            category_label="交互与通知",
            slot_id="notifications.plan-ready",
            slot_label="计划就绪通知",
            activation_mode="multiple",
            category_order=90,
            slot_order=20,
            plugin_order=index * 10,
            hooks={"render_plan_notification": handler},
            default_enabled=enabled,
            failure_mode="isolate",
            swap_policy="anytime",
            permissions=["mission.read"],
        )
        for index, (plugin_id, name, description, handler, enabled) in enumerate(values, start=1)
    ]
