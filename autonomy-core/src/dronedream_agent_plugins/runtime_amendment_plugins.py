from __future__ import annotations

import re
from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin

ACTION_PATTERNS = [
    ("safe_land", ("安全降落", "立即降落", "land now", "safe land")),
    ("return_home", ("返航", "回来", "return home", "come back")),
    ("set_speed", ("快一点", "慢一点", "速度", "speed", "faster", "slower")),
    ("set_return_point", ("返航点", "返回点", "return point")),
    ("set_coverage", ("覆盖范围", "coverage")),
    ("camera_control", ("拍照", "录像", "相机", "camera", "record")),
    ("payload_control", ("释放载荷", "放下", "payload", "release")),
    ("set_avoidance", ("避障", "绕开", "avoid")),
    ("follow_target", ("跟随", "follow")),
    ("operator_takeover", ("接管", "人工控制", "takeover")),
    (
        "redirect",
        (
            "改去",
            "改到",
            "改道",
            "换到",
            "换成",
            "改变目的地",
            "不要继续去",
            "instead",
            "reroute",
            "redirect",
            "change destination",
        ),
    ),
    # "先悬停，再改道" is one redirect with a safety precondition, not a
    # persistent-pause command. Pause/resume therefore have lower precedence
    # than every concrete amendment above.
    ("pause", ("暂停", "先停", "悬停", "pause", "hold")),
    ("resume", ("继续", "恢复", "resume", "continue")),
]


def _classify(
    *, value: dict[str, object], message: Any, prepared: Any, **_: Any
) -> dict[str, object]:
    normalized = message.text.casefold()
    action = str(value.get("requested_action", "replan"))
    for candidate, patterns in ACTION_PATTERNS:
        if any(pattern in normalized for pattern in patterns):
            action = candidate
            break
    parameters = dict(value.get("parameters", {}))
    speed_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:m/s|米每秒)", normalized)
    if action == "set_speed" and speed_match:
        parameters["maximum_speed_mps"] = float(speed_match.group(1))
    if action == "camera_control" and "command" not in parameters:
        if any(token in normalized for token in ("停止录像", "停止录制", "stop video")):
            parameters["command"] = "stop_video"
        elif any(token in normalized for token in ("录像", "录制", "start video", "record")):
            parameters["command"] = "start_video"
        elif any(token in normalized for token in ("拍照", "照片", "take photo")):
            parameters["command"] = "take_photo"
    if action == "payload_control" and "operation" not in parameters:
        if any(token in normalized for token in ("释放", "放下", "卸载", "detach", "release")):
            parameters["operation"] = "detach"
        elif any(token in normalized for token in ("抓取", "挂载", "拿起", "attach", "pickup")):
            parameters["operation"] = "attach"
    if action == "set_avoidance" and "enabled" not in parameters:
        parameters["enabled"] = not any(
            token in normalized for token in ("关闭避障", "禁用避障", "disable avoidance")
        )
    target_entity = value.get("target_entity")
    if action == "return_home":
        target_entity = prepared.contract.return_node
    return {
        **value,
        "requested_action": action,
        "target_entity": target_entity,
        "parameters": parameters,
        "requires_plan_revision": action not in {"resume", "pause", "safe_land"},
    }


def _conservative_directive(
    *, classification: Any, acknowledgement: Any, prepared: Any, **_: Any
) -> dict[str, object]:
    action = classification.requested_action
    parameters = dict(classification.parameters)
    issues: list[str] = []
    if action == "set_speed":
        speed = parameters.get("maximum_speed_mps")
        if speed is None:
            issues.append("SPEED_VALUE_REQUIRED")
        elif not 0.1 <= float(speed) <= 3.0:
            issues.append("SPEED_OUTSIDE_QUALIFIED_ENVELOPE")
    if action in {"redirect", "set_return_point", "follow_target"} and not (
        classification.target_entity
    ):
        issues.append("TARGET_ENTITY_REQUIRED")
    if (
        action == "set_coverage"
        and not classification.target_entity
        and not parameters.get("polygon_enu_m")
    ):
        issues.append("COVERAGE_TARGET_OR_POLYGON_REQUIRED")
    if action == "camera_control" and parameters.get("command") not in {
        "take_photo",
        "start_video",
        "stop_video",
    }:
        issues.append("CAMERA_COMMAND_REQUIRED")
    if action == "camera_control":
        parameters.setdefault("component_id", 100)
    if action == "payload_control":
        operation = parameters.get("operation")
        if operation not in {"attach", "detach"}:
            issues.append("PAYLOAD_OPERATION_REQUIRED")
        elif prepared.contract.vehicle_asset_id == "dronedream.my-drone.v1":
            parameters.setdefault("protocol", "gazebo-transport")
            parameters.setdefault(
                "topic",
                f"/model/my_drone/takeout_payload/{operation}",
            )
            parameters.setdefault(
                "output_topic",
                "/model/my_drone/takeout_payload/state",
            )
        elif parameters.get("protocol") not in {"gazebo-transport", "mavsdk-actuator"}:
            issues.append("PAYLOAD_TRANSPORT_REQUIRED")
    if action == "set_avoidance" and not isinstance(parameters.get("enabled"), bool):
        issues.append("AVOIDANCE_BOOLEAN_REQUIRED")
    if action == "follow_target":
        topic = parameters.get("target_pose_topic")
        if not isinstance(topic, str) or not topic.startswith("/"):
            issues.append("FOLLOW_TARGET_POSE_TOPIC_REQUIRED")
        parameters.setdefault("follow_duration_seconds", 30.0)
        parameters.setdefault("standoff_m", 2.0)
        parameters.setdefault("altitude_offset_m", 1.0)
        parameters.setdefault("maximum_speed_mps", 1.0)
        parameters.setdefault("target_update_rate_hz", 2.0)
        numeric_limits = {
            "follow_duration_seconds": (1.0, 300.0),
            "standoff_m": (0.5, 20.0),
            "altitude_offset_m": (-5.0, 20.0),
            "maximum_speed_mps": (0.1, 3.0),
            "target_update_rate_hz": (0.5, 10.0),
        }
        for name, (minimum, maximum) in numeric_limits.items():
            value = parameters.get(name)
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not minimum <= float(value) <= maximum
            ):
                issues.append(f"FOLLOW_{name.upper()}_INVALID")
    return {
        "action": action,
        "parameters": parameters,
        "requires_stable_hold": True,
        "requires_plan_revision": classification.requires_plan_revision,
        "requires_core_authorization": True,
        "issue_codes": issues,
    }


def plugin_definitions() -> list[PluginDefinition]:
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id="runtime.amendment-language-classifier",
            name="运行期改令分类",
            description="把改目的地、速度、暂停、返航、相机、载荷和接管等指令规范化。",
            capability_id="runtime.amendment-language-classifier.classify",
            capability_kind="runtime-amendment",
            capability_name="运行期改令分类",
            capability_description="模型分类后再由确定性语言规则收紧动作类型。",
            category_id="runtime",
            category_label="运行期与在线换路",
            slot_id="runtime.amendment-classifier",
            slot_label="改令分类",
            activation_mode="single",
            category_order=70,
            slot_order=10,
            plugin_order=10,
            hooks={"classify_amendment": _classify},
            default_enabled=True,
            failure_mode="fail-closed",
            swap_policy="safe-hold",
        ),
        hook_plugin(
            module_name=__name__,
            plugin_id="runtime.amendment-conservative",
            name="保守改令策略",
            description="所有改令先稳定悬停，再检查参数、计划修订和核心授权。",
            capability_id="runtime.amendment-conservative.apply",
            capability_kind="runtime-amendment",
            capability_name="保守改令策略",
            capability_description="生成无执行权限的结构化改令指令。",
            category_id="runtime",
            category_label="运行期与在线换路",
            slot_id="runtime.amendment-policy",
            slot_label="改令应用策略",
            activation_mode="single",
            category_order=70,
            slot_order=20,
            plugin_order=10,
            hooks={"apply_amendment": _conservative_directive},
            default_enabled=True,
            failure_mode="fail-closed",
            swap_policy="safe-hold",
        ),
    ]
