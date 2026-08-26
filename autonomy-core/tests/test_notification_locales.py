from __future__ import annotations

from dronedream_agent_plugins.notification_plugins import (
    _operator_checklist,
    _plan_ready,
    _planning_metrics,
)


def _summary(locale: str) -> dict[str, object]:
    return {
        "locale": locale,
        "goal": "inspect the school gate" if locale == "en-US" else "巡检学校门口",
        "model_calls": 5,
        "minimum_clearance_m": 1.25,
        "contract_id": "contract-1",
        "plan_revision_id": "revision-1",
        "plugin_snapshot_id": "snapshot-1",
        "planning_attempts": 2,
        "plugin_catalog_sha256": "a" * 64,
        "target_entity": "school-gate",
        "return_entity": "office-pad",
    }


def test_plan_notifications_are_fully_english_for_english_locale() -> None:
    summary = _summary("en-US")
    contents = [
        _plan_ready(summary=summary)["content"],
        _planning_metrics(summary=summary)["content"],
        _operator_checklist(summary=summary)["content"],
    ]
    assert contents == [
        "Plan ready: inspect the school gate",
        "Planning evidence: 5 model calls, minimum clearance 1.25 m",
        "Before execution, confirm the target, return location, map, drone, and mission contract.",
    ]
    assert all(not any("\u3400" <= char <= "\u9fff" for char in value) for value in contents)


def test_plan_notifications_remain_chinese_for_chinese_locale() -> None:
    summary = _summary("zh-CN")
    contents = [
        _plan_ready(summary=summary)["content"],
        _planning_metrics(summary=summary)["content"],
        _operator_checklist(summary=summary)["content"],
    ]
    assert contents == [
        "计划已生成：巡检学校门口",
        "规划证据：5 次模型调用，最小净空 1.25 m",
        "执行前请确认目标、返程位置、地图、无人机和任务合同。",
    ]
