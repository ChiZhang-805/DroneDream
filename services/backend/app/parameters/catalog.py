"""Curated, versioned catalog of multicopter PX4 tuning parameters.

Hard bounds follow the PX4 parameter reference where it declares finite limits.
For gains where upstream has no finite maximum, DroneDream deliberately supplies
a conservative finite guardrail. Safe bounds are narrower DroneDream defaults;
they are not claims about safe values for every physical airframe.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Literal, TypedDict, cast

from app.parameters.models import (
    Bounds,
    LocalizedText,
    Number,
    ParameterApplyPolicy,
    ParameterChoice,
    ParameterCompatibility,
    ParameterDefinition,
    ParameterDependency,
    ParameterDependencyKind,
    ParameterExpertise,
    ParameterRisk,
    ParameterValueType,
    TuningPreset,
)

CATALOG_VERSION = "dronedream.px4.multicopter.builtin"
CATALOG_SOURCE = "PX4 v1.16, v1.17, and main parameter references checked 2026-07-10"
CATALOG_SOURCE_URL = "https://docs.px4.io/main/en/advanced_config/parameter_reference"
SUPPORTED_PX4_VERSIONS = ("v1.16", "v1.17", "main")
SUPPORTED_VEHICLE_TYPES = ("multicopter",)
SUPPORTED_AIRFRAME_FAMILIES = (
    "quadrotor",
    "hexarotor",
    "octocopter",
    "custom_multicopter",
)
SUPPORTED_TRIAL_METRICS = (
    "rmse",
    "max_error",
    "overshoot_count",
    "completion_time",
    "crash_flag",
    "timeout_flag",
    "score",
    "final_error",
    "instability_flag",
)

# Explicit compatibility aliases remain narrow: an unknown identifier must
# never silently select whatever catalog happens to be installed on the server.
CATALOG_VERSION_ALIASES: dict[str, str] = {
    "builtin-v1": CATALOG_VERSION,
    "px4-v1.16": CATALOG_VERSION,
    "px4-v1.17": CATALOG_VERSION,
    "px4-main": CATALOG_VERSION,
}

GROUPS: tuple[dict[str, object], ...] = (
    {
        "id": "xy_position_velocity",
        "order": 10,
        "label": {"en": "XY position and velocity", "zh-CN": "XY 位置与速度环"},
        "description": {
            "en": "Horizontal position-to-velocity and velocity-to-acceleration gains.",
            "zh-CN": "水平位置到速度、速度到加速度的串级控制增益。",
        },
    },
    {
        "id": "z_position_velocity",
        "order": 20,
        "label": {"en": "Z position and velocity", "zh-CN": "Z 轴位置与速度环"},
        "description": {
            "en": "Vertical position and climb-rate controller gains.",
            "zh-CN": "高度位置与升降速度控制增益。",
        },
    },
    {
        "id": "attitude",
        "order": 30,
        "label": {"en": "Attitude", "zh-CN": "姿态环"},
        "description": {
            "en": "Attitude-error to angular-rate gains.",
            "zh-CN": "姿态误差到角速度指令的控制增益。",
        },
    },
    {
        "id": "angular_rate",
        "order": 40,
        "label": {"en": "Angular rate", "zh-CN": "角速度环"},
        "description": {
            "en": "Inner-loop roll, pitch, and yaw rate gains.",
            "zh-CN": "横滚、俯仰和偏航的内层角速度增益。",
        },
    },
    {
        "id": "thrust_and_authority",
        "order": 45,
        "label": {"en": "Thrust and control authority", "zh-CN": "推力与控制权"},
        "description": {
            "en": "Hover thrust, thrust limits, motor response, and mixer authority.",
            "zh-CN": "悬停推力、推力限制、电机响应与混控控制权。",
        },
    },
    {
        "id": "filters",
        "order": 50,
        "label": {"en": "Controller filters", "zh-CN": "控制器滤波"},
        "description": {
            "en": "Gyroscope and D-term filtering that trades noise against latency.",
            "zh-CN": "在噪声抑制与控制延迟之间权衡的陀螺仪与 D 项滤波。",
        },
    },
    {
        "id": "motion_limits",
        "order": 60,
        "label": {"en": "Motion limits", "zh-CN": "运动限制"},
        "description": {
            "en": "Velocity, acceleration, and jerk limits used by position control.",
            "zh-CN": "位置控制使用的速度、加速度与加加速度限制。",
        },
    },
)

WORKFLOW_PRECONDITIONS: tuple[dict[str, object], ...] = (
    {
        "id": "sitl_or_props_removed",
        "label": {"en": "Use SITL or remove propellers", "zh-CN": "使用 SITL 或拆除桨叶"},
        "description": {
            "en": "Run automated search in simulation before any restrained or flight test.",
            "zh-CN": "任何系留或实飞测试前，先在仿真中完成自动搜索。",
        },
    },
    {
        "id": "vehicle_stable",
        "label": {"en": "Stable baseline", "zh-CN": "稳定的基线参数"},
        "description": {
            "en": "The baseline must take off, hover, and land without strong oscillation.",
            "zh-CN": "基线参数必须能在无强烈振荡的情况下起飞、悬停和降落。",
        },
    },
    {
        "id": "high_rate_logging",
        "label": {"en": "High-rate logging", "zh-CN": "高频日志"},
        "description": {
            "en": "Capture setpoint and response signals at a rate suitable for loop analysis.",
            "zh-CN": "以适合控制环分析的频率记录设定值和响应信号。",
        },
    },
    {
        "id": "disable_airmode",
        "label": {"en": "Disable airmode while tuning", "zh-CN": "调参时禁用 Air-mode"},
        "description": {
            "en": "Use MC_AIRMODE=0 for the rate-tuning workflow, then restore deliberately.",
            "zh-CN": "角速度调优流程中使用 MC_AIRMODE=0，完成后再有意识地恢复。",
        },
    },
    {
        "id": "rate_loop_validated",
        "label": {"en": "Rate loop validated", "zh-CN": "角速度环已验证"},
        "description": {
            "en": "Complete and accept inner rate-loop tuning before outer loops.",
            "zh-CN": "进入外环前，先完成并验收内层角速度环。",
        },
    },
    {
        "id": "attitude_loop_validated",
        "label": {"en": "Attitude loop validated", "zh-CN": "姿态环已验证"},
        "description": {
            "en": "Complete attitude tracking validation before position tuning.",
            "zh-CN": "位置调优前先完成姿态跟踪验证。",
        },
    },
)


class _GroupDefaults(TypedDict):
    control_loop: str
    tuning_stage: int
    metrics: tuple[str, ...]
    evidence_signals: tuple[str, ...]
    flight_modes: tuple[str, ...]
    preconditions: tuple[str, ...]


_GROUP_DEFAULTS: dict[str, _GroupDefaults] = {
    "angular_rate": {
        "control_loop": "angular_rate",
        "tuning_stage": 10,
        "metrics": ("rmse", "max_error", "overshoot_count", "instability_flag"),
        "evidence_signals": (
            "vehicle_rates_setpoint",
            "vehicle_angular_velocity",
            "vehicle_torque_setpoint",
        ),
        "flight_modes": ("acro", "stabilized"),
        "preconditions": (
            "sitl_or_props_removed",
            "vehicle_stable",
            "high_rate_logging",
            "disable_airmode",
        ),
    },
    "attitude": {
        "control_loop": "attitude",
        "tuning_stage": 20,
        "metrics": ("rmse", "max_error", "overshoot_count", "instability_flag"),
        "evidence_signals": (
            "vehicle_attitude_setpoint",
            "vehicle_attitude",
            "vehicle_angular_velocity",
        ),
        "flight_modes": ("stabilized",),
        "preconditions": ("rate_loop_validated",),
    },
    "thrust_and_authority": {
        "control_loop": "thrust_model",
        "tuning_stage": 25,
        "metrics": ("rmse", "max_error", "final_error", "instability_flag"),
        "evidence_signals": (
            "vehicle_thrust_setpoint",
            "actuator_motors",
            "vehicle_local_position",
        ),
        "flight_modes": ("altitude", "position"),
        "preconditions": ("rate_loop_validated",),
    },
    "filters": {
        "control_loop": "sensor_filter",
        "tuning_stage": 30,
        "metrics": ("rmse", "overshoot_count", "instability_flag"),
        "evidence_signals": (
            "sensor_gyro",
            "vehicle_angular_velocity",
            "vehicle_angular_acceleration",
        ),
        "flight_modes": ("acro", "stabilized"),
        "preconditions": ("high_rate_logging", "rate_loop_validated"),
    },
    "xy_position_velocity": {
        "control_loop": "horizontal_position_velocity",
        "tuning_stage": 40,
        "metrics": ("rmse", "max_error", "overshoot_count", "completion_time"),
        "evidence_signals": ("trajectory_setpoint", "vehicle_local_position"),
        "flight_modes": ("position", "offboard"),
        "preconditions": ("attitude_loop_validated",),
    },
    "z_position_velocity": {
        "control_loop": "vertical_position_velocity",
        "tuning_stage": 50,
        "metrics": ("rmse", "max_error", "overshoot_count", "completion_time"),
        "evidence_signals": ("trajectory_setpoint", "vehicle_local_position"),
        "flight_modes": ("altitude", "position", "offboard"),
        "preconditions": ("attitude_loop_validated",),
    },
    "motion_limits": {
        "control_loop": "trajectory_limits",
        "tuning_stage": 60,
        "metrics": ("rmse", "max_error", "completion_time", "instability_flag"),
        "evidence_signals": (
            "trajectory_setpoint",
            "vehicle_local_position",
            "control_allocator_status",
        ),
        "flight_modes": ("position", "mission", "offboard"),
        "preconditions": ("attitude_loop_validated",),
    },
}


def _text(en: str, zh_cn: str) -> LocalizedText:
    return LocalizedText(en=en, zh_cn=zh_cn)


def _dep(
    kind: ParameterDependencyKind,
    parameter: str,
    en: str,
    zh_cn: str,
) -> ParameterDependency:
    return ParameterDependency(
        kind=kind,
        parameter=parameter,
        description=_text(en, zh_cn),
    )


def _axes_for(name: str) -> tuple[str, ...]:
    if "ROLL" in name:
        return ("roll",)
    if "PITCH" in name:
        return ("pitch",)
    if "YAW" in name:
        return ("yaw",)
    if "_XY_" in name or name.startswith("MPC_XY"):
        return ("x", "y")
    if "_Z_" in name or name.startswith("MPC_Z"):
        return ("z",)
    if "_HOR" in name or "JERK" in name:
        return ("x", "y")
    if "TILT" in name:
        return ("roll", "pitch")
    if "THR" in name or name == "MC_AIRMODE":
        return ("collective",)
    return ("roll", "pitch", "yaw")


def _control_loop_for(name: str, group: str) -> str:
    if group == "xy_position_velocity":
        return "horizontal_velocity" if "_VEL_" in name else "horizontal_position"
    if group == "z_position_velocity":
        return "vertical_velocity" if "_VEL_" in name else "vertical_position"
    return str(_GROUP_DEFAULTS[group]["control_loop"])


def _risk_note(risk: ParameterRisk) -> LocalizedText:
    if risk == "high":
        return _text(
            (
                "An unsafe value can cause oscillation, loss of authority, or a crash; "
                "validate in SITL."
            ),
            "不安全的取值可能导致振荡、控制权丢失或坠机；必须先在 SITL 中验证。",
        )
    if risk == "medium":
        return _text(
            "Validate limits and transients across nominal and disturbed scenarios.",
            "应在标称与扰动场景中验证限制和瞬态响应。",
        )
    return _text(
        "Keep a reproducible baseline and verify the resulting response.",
        "请保留可复现的基线并验证修改后的响应。",
    )


def _p(
    name: str,
    *,
    hard: tuple[Number, Number],
    safe: tuple[Number, Number],
    step: Number,
    default: Number,
    group: str,
    risk: ParameterRisk,
    label: tuple[str, str],
    description: tuple[str, str],
    unit: str = "",
    value_type: ParameterValueType = "float",
    reboot: bool = False,
    dependencies: tuple[ParameterDependency, ...] = (),
    control_loop: str | None = None,
    axes: tuple[str, ...] | None = None,
    tuning_stage: int | None = None,
    expertise: ParameterExpertise | None = None,
    apply_policy: ParameterApplyPolicy | None = None,
    recommended_metrics: tuple[str, ...] | None = None,
    evidence_signals: tuple[str, ...] | None = None,
    flight_modes: tuple[str, ...] | None = None,
    preconditions: tuple[str, ...] | None = None,
    bounds_source: Literal["px4", "px4_and_dronedream_guardrail"] = "px4",
    choices: tuple[tuple[Number, str, str], ...] = (),
) -> ParameterDefinition:
    defaults = _GROUP_DEFAULTS[group]
    return ParameterDefinition(
        name=name,
        value_type=value_type,
        unit=unit,
        hard_bounds=Bounds(*hard),
        safe_bounds=Bounds(*safe),
        step=step,
        default=default,
        group=group,
        risk=risk,
        requires_reboot=reboot,
        label=_text(*label),
        description=_text(*description),
        dependencies=dependencies,
        control_loop=control_loop or _control_loop_for(name, group),
        axes=axes or _axes_for(name),
        tuning_stage=tuning_stage or defaults["tuning_stage"],
        expertise=expertise
        or (
            "expert"
            if group == "filters"
            else ("guided" if risk in {"low", "medium"} else "advanced")
        ),
        apply_policy=apply_policy
        or ("reboot" if reboot else ("disarmed" if risk == "high" else "live")),
        compatibility=ParameterCompatibility(
            px4_versions=SUPPORTED_PX4_VERSIONS,
            vehicle_types=SUPPORTED_VEHICLE_TYPES,
            airframe_families=SUPPORTED_AIRFRAME_FAMILIES,
        ),
        recommended_metrics=recommended_metrics or defaults["metrics"],
        evidence_signals=evidence_signals or defaults["evidence_signals"],
        flight_modes=flight_modes or defaults["flight_modes"],
        preconditions=preconditions or defaults["preconditions"],
        risk_note=_risk_note(risk),
        source_url=f"{CATALOG_SOURCE_URL}#{name}",
        bounds_source=bounds_source,
        choices=tuple(
            ParameterChoice(value=value, label=_text(en, zh_cn))
            for value, en, zh_cn in choices
        ),
    )


PARAMETERS: tuple[ParameterDefinition, ...] = (
    _p(
        "MPC_XY_P",
        hard=(0.0, 2.0),
        safe=(0.6, 1.3),
        step=0.1,
        default=0.95,
        group="xy_position_velocity",
        risk="medium",
        label=("Horizontal position P", "水平位置 P 增益"),
        description=(
            "Corrective horizontal velocity per metre of position error.",
            "每米水平位置误差对应的修正速度。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MPC_XY_VEL_P_ACC",
                "Tune the downstream velocity loop before or together with this outer loop.",
                "应先调好下游速度环，或与该外环联动验证。",
            ),
        ),
    ),
    _p(
        "MPC_XY_VEL_P_ACC",
        hard=(1.2, 5.0),
        safe=(1.2, 2.8),
        step=0.1,
        default=1.8,
        group="xy_position_velocity",
        risk="medium",
        label=("Horizontal velocity P", "水平速度 P 增益"),
        description=(
            "Corrective acceleration per horizontal velocity error.",
            "水平速度误差对应的修正加速度。",
        ),
    ),
    _p(
        "MPC_XY_VEL_I_ACC",
        hard=(0.0, 60.0),
        safe=(0.1, 1.0),
        step=0.02,
        default=0.4,
        group="xy_position_velocity",
        risk="high",
        label=("Horizontal velocity I", "水平速度 I 增益"),
        description=(
            "Integral correction for steady horizontal disturbances.",
            "用于消除持续水平扰动引起的稳态误差。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MPC_XY_VEL_P_ACC",
                "Validate with the velocity P gain.",
                "需与速度 P 增益联动验证。",
            ),
        ),
    ),
    _p(
        "MPC_XY_VEL_D_ACC",
        hard=(0.1, 2.0),
        safe=(0.1, 0.5),
        step=0.02,
        default=0.2,
        group="xy_position_velocity",
        risk="high",
        label=("Horizontal velocity D", "水平速度 D 增益"),
        description=(
            "Damping from horizontal velocity-error derivative.",
            "由水平速度误差变化率产生的阻尼修正。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MPC_XY_VEL_P_ACC",
                "Validate with the velocity P gain.",
                "需与速度 P 增益联动验证。",
            ),
        ),
    ),
    _p(
        "MPC_Z_P",
        hard=(0.1, 1.5),
        safe=(0.6, 1.3),
        step=0.1,
        default=1.0,
        group="z_position_velocity",
        risk="medium",
        label=("Vertical position P", "垂直位置 P 增益"),
        description=(
            "Corrective climb rate per metre of altitude error.",
            "每米高度误差对应的修正升降速度。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MPC_Z_VEL_P_ACC",
                "Tune the vertical velocity loop first.",
                "建议先完成垂直速度环调优。",
            ),
        ),
    ),
    _p(
        "MPC_Z_VEL_P_ACC",
        hard=(2.0, 15.0),
        safe=(2.5, 8.0),
        step=0.1,
        default=4.0,
        group="z_position_velocity",
        risk="medium",
        label=("Vertical velocity P", "垂直速度 P 增益"),
        description=(
            "Corrective vertical acceleration per climb-rate error.",
            "升降速度误差对应的垂直修正加速度。",
        ),
    ),
    _p(
        "MPC_Z_VEL_I_ACC",
        hard=(0.2, 3.0),
        safe=(0.5, 2.5),
        step=0.1,
        default=2.0,
        group="z_position_velocity",
        risk="high",
        label=("Vertical velocity I", "垂直速度 I 增益"),
        description=(
            "Integral correction for sustained vertical error.",
            "用于消除持续垂直误差的积分修正。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MPC_Z_VEL_P_ACC",
                "Validate with the vertical velocity P gain.",
                "需与垂直速度 P 增益联动验证。",
            ),
        ),
    ),
    _p(
        "MPC_Z_VEL_D_ACC",
        hard=(0.0, 2.0),
        safe=(0.0, 0.5),
        step=0.02,
        default=0.0,
        group="z_position_velocity",
        risk="high",
        label=("Vertical velocity D", "垂直速度 D 增益"),
        description=(
            "Damping from vertical velocity-error derivative.",
            "由垂直速度误差变化率产生的阻尼修正。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MPC_Z_VEL_P_ACC",
                "Validate with the vertical velocity P gain.",
                "需与垂直速度 P 增益联动验证。",
            ),
        ),
    ),
    _p(
        "MC_ROLL_P",
        hard=(0.0, 12.0),
        safe=(2.0, 8.0),
        step=0.1,
        default=6.5,
        group="attitude",
        risk="high",
        label=("Roll attitude P", "横滚姿态 P 增益"),
        description=(
            "Desired roll rate per radian of roll attitude error.",
            "每弧度横滚姿态误差对应的目标横滚角速度。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_PITCH_P",
                "Roll and pitch are normally validated as a pair.",
                "横滚与俯仰通常需要成对验证。",
            ),
        ),
    ),
    _p(
        "MC_PITCH_P",
        hard=(0.0, 12.0),
        safe=(2.0, 8.0),
        step=0.1,
        default=6.5,
        group="attitude",
        risk="high",
        label=("Pitch attitude P", "俯仰姿态 P 增益"),
        description=(
            "Desired pitch rate per radian of pitch attitude error.",
            "每弧度俯仰姿态误差对应的目标俯仰角速度。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_ROLL_P",
                "Roll and pitch are normally validated as a pair.",
                "横滚与俯仰通常需要成对验证。",
            ),
        ),
    ),
    _p(
        "MC_YAW_P",
        hard=(0.0, 5.0),
        safe=(1.0, 4.0),
        step=0.1,
        default=2.8,
        group="attitude",
        risk="high",
        label=("Yaw attitude P", "偏航姿态 P 增益"),
        description=(
            "Desired yaw rate per radian of yaw attitude error.",
            "每弧度偏航姿态误差对应的目标偏航角速度。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_YAWRATE_P",
                "Validate against yaw-rate tracking authority.",
                "需结合偏航角速度跟踪能力验证。",
            ),
        ),
    ),
    _p(
        "MC_ROLLRATE_P",
        hard=(0.01, 0.5),
        safe=(0.08, 0.25),
        step=0.01,
        default=0.15,
        group="angular_rate",
        risk="high",
        label=("Roll rate P", "横滚角速度 P 增益"),
        description=(
            "Proportional torque command for roll-rate error.",
            "横滚角速度误差对应的比例力矩指令。",
        ),
    ),
    _p(
        "MC_ROLLRATE_I",
        hard=(0.0, 1.0),
        safe=(0.05, 0.4),
        step=0.01,
        default=0.2,
        group="angular_rate",
        risk="high",
        label=("Roll rate I", "横滚角速度 I 增益"),
        description=(
            "Integral correction for persistent roll-rate error.",
            "持续横滚角速度误差的积分修正。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_ROLLRATE_P",
                "Tune as part of the roll-rate PID set.",
                "应作为横滚角速度 PID 组合的一部分调节。",
            ),
        ),
    ),
    _p(
        "MC_ROLLRATE_D",
        hard=(0.0, 0.01),
        safe=(0.001, 0.006),
        step=0.0005,
        default=0.003,
        group="angular_rate",
        risk="high",
        label=("Roll rate D", "横滚角速度 D 增益"),
        description=(
            "Derivative damping for fast roll oscillations.",
            "用于抑制快速横滚振荡的微分阻尼。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_ROLLRATE_P",
                "Tune as part of the roll-rate PID set.",
                "应作为横滚角速度 PID 组合的一部分调节。",
            ),
        ),
    ),
    _p(
        "MC_PITCHRATE_P",
        hard=(0.01, 0.6),
        safe=(0.08, 0.3),
        step=0.01,
        default=0.15,
        group="angular_rate",
        risk="high",
        label=("Pitch rate P", "俯仰角速度 P 增益"),
        description=(
            "Proportional torque command for pitch-rate error.",
            "俯仰角速度误差对应的比例力矩指令。",
        ),
    ),
    _p(
        "MC_PITCHRATE_I",
        hard=(0.0, 1.0),
        safe=(0.05, 0.4),
        step=0.01,
        default=0.2,
        group="angular_rate",
        risk="high",
        label=("Pitch rate I", "俯仰角速度 I 增益"),
        description=(
            "Integral correction for persistent pitch-rate error.",
            "持续俯仰角速度误差的积分修正。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_PITCHRATE_P",
                "Tune as part of the pitch-rate PID set.",
                "应作为俯仰角速度 PID 组合的一部分调节。",
            ),
        ),
    ),
    _p(
        "MC_PITCHRATE_D",
        hard=(0.0, 0.01),
        safe=(0.001, 0.006),
        step=0.0005,
        default=0.003,
        group="angular_rate",
        risk="high",
        label=("Pitch rate D", "俯仰角速度 D 增益"),
        description=(
            "Derivative damping for fast pitch oscillations.",
            "用于抑制快速俯仰振荡的微分阻尼。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_PITCHRATE_P",
                "Tune as part of the pitch-rate PID set.",
                "应作为俯仰角速度 PID 组合的一部分调节。",
            ),
        ),
    ),
    _p(
        "MC_YAWRATE_P",
        hard=(0.0, 0.6),
        safe=(0.05, 0.35),
        step=0.01,
        default=0.2,
        group="angular_rate",
        risk="high",
        label=("Yaw rate P", "偏航角速度 P 增益"),
        description=(
            "Proportional torque command for yaw-rate error.",
            "偏航角速度误差对应的比例力矩指令。",
        ),
    ),
    _p(
        "MC_YAWRATE_I",
        hard=(0.0, 0.5),
        safe=(0.02, 0.25),
        step=0.01,
        default=0.1,
        group="angular_rate",
        risk="high",
        label=("Yaw rate I", "偏航角速度 I 增益"),
        description=(
            "Integral correction for persistent yaw-rate error.",
            "持续偏航角速度误差的积分修正。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_YAWRATE_P",
                "Tune with yaw-rate P gain.",
                "需与偏航角速度 P 增益联动调节。",
            ),
        ),
    ),
    _p(
        "MC_YAWRATE_D",
        hard=(0.0, 0.01),
        safe=(0.0, 0.003),
        step=0.0005,
        default=0.0,
        group="angular_rate",
        risk="high",
        label=("Yaw rate D", "偏航角速度 D 增益"),
        description=(
            "Derivative damping for fast yaw oscillations; most multicopters keep it near zero.",
            "用于抑制快速偏航振荡的微分阻尼；多数多旋翼应保持接近零。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_YAWRATE_P",
                "Tune only after yaw-rate P tracking is stable.",
                "仅在偏航角速度 P 跟踪稳定后再调节。",
            ),
        ),
        bounds_source="px4_and_dronedream_guardrail",
    ),
    _p(
        "MC_ROLLRATE_K",
        hard=(0.01, 5.0),
        safe=(0.5, 2.0),
        step=0.0005,
        default=1.0,
        group="angular_rate",
        risk="high",
        label=("Roll rate global gain", "横滚角速度全局增益"),
        description=(
            "Scales roll rate P, I, and D terms and selects the controller form with P.",
            "缩放横滚角速度 P、I、D 项，并与 P 一起决定控制器形式。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_ROLLRATE_P",
                "K and P jointly define the mixed PID form.",
                "K 与 P 共同定义混合 PID 形式。",
            ),
        ),
    ),
    _p(
        "MC_PITCHRATE_K",
        hard=(0.01, 5.0),
        safe=(0.5, 2.0),
        step=0.0005,
        default=1.0,
        group="angular_rate",
        risk="high",
        label=("Pitch rate global gain", "俯仰角速度全局增益"),
        description=(
            "Scales pitch rate P, I, and D terms and selects the controller form with P.",
            "缩放俯仰角速度 P、I、D 项，并与 P 一起决定控制器形式。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_PITCHRATE_P",
                "K and P jointly define the mixed PID form.",
                "K 与 P 共同定义混合 PID 形式。",
            ),
        ),
    ),
    _p(
        "MC_YAWRATE_K",
        hard=(0.01, 5.0),
        safe=(0.5, 2.0),
        step=0.0005,
        default=1.0,
        group="angular_rate",
        risk="high",
        label=("Yaw rate global gain", "偏航角速度全局增益"),
        description=(
            "Scales yaw rate P, I, and D terms and selects the controller form with P.",
            "缩放偏航角速度 P、I、D 项，并与 P 一起决定控制器形式。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_YAWRATE_P",
                "K and P jointly define the mixed PID form.",
                "K 与 P 共同定义混合 PID 形式。",
            ),
        ),
    ),
    _p(
        "MC_ROLLRATE_FF",
        hard=(0.0, 2.0),
        safe=(0.0, 0.5),
        step=0.01,
        default=0.0,
        group="angular_rate",
        risk="high",
        label=("Roll rate feed-forward", "横滚角速度前馈"),
        description=(
            "Feed-forward torque for roll-rate setpoint tracking.",
            "用于横滚角速度设定值跟踪的前馈力矩。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_ROLLRATE_P",
                "Add feed-forward only after feedback gains are stable.",
                "仅在反馈增益稳定后再增加前馈。",
            ),
        ),
        bounds_source="px4_and_dronedream_guardrail",
    ),
    _p(
        "MC_PITCHRATE_FF",
        hard=(0.0, 2.0),
        safe=(0.0, 0.5),
        step=0.01,
        default=0.0,
        group="angular_rate",
        risk="high",
        label=("Pitch rate feed-forward", "俯仰角速度前馈"),
        description=(
            "Feed-forward torque for pitch-rate setpoint tracking.",
            "用于俯仰角速度设定值跟踪的前馈力矩。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_PITCHRATE_P",
                "Add feed-forward only after feedback gains are stable.",
                "仅在反馈增益稳定后再增加前馈。",
            ),
        ),
        bounds_source="px4_and_dronedream_guardrail",
    ),
    _p(
        "MC_YAWRATE_FF",
        hard=(0.0, 2.0),
        safe=(0.0, 0.5),
        step=0.01,
        default=0.0,
        group="angular_rate",
        risk="high",
        label=("Yaw rate feed-forward", "偏航角速度前馈"),
        description=(
            "Feed-forward torque for yaw-rate setpoint tracking.",
            "用于偏航角速度设定值跟踪的前馈力矩。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_YAWRATE_P",
                "Add feed-forward only after feedback gains are stable.",
                "仅在反馈增益稳定后再增加前馈。",
            ),
        ),
        bounds_source="px4_and_dronedream_guardrail",
    ),
    _p(
        "MC_ROLLRATE_MAX",
        hard=(0.0, 1800.0),
        safe=(100.0, 720.0),
        step=5.0,
        default=220.0,
        group="angular_rate",
        risk="medium",
        unit="deg/s",
        label=("Maximum roll rate", "最大横滚角速度"),
        description=(
            "Roll-rate limit for manual and autonomous modes except Acro.",
            "除 Acro 外手动和自主模式的横滚角速度限制。",
        ),
    ),
    _p(
        "MC_PITCHRATE_MAX",
        hard=(0.0, 1800.0),
        safe=(100.0, 720.0),
        step=5.0,
        default=220.0,
        group="angular_rate",
        risk="medium",
        unit="deg/s",
        label=("Maximum pitch rate", "最大俯仰角速度"),
        description=(
            "Pitch-rate limit for manual and autonomous modes except Acro.",
            "除 Acro 外手动和自主模式的俯仰角速度限制。",
        ),
    ),
    _p(
        "MC_YAWRATE_MAX",
        hard=(0.0, 1800.0),
        safe=(60.0, 360.0),
        step=5.0,
        default=200.0,
        group="angular_rate",
        risk="medium",
        unit="deg/s",
        label=("Maximum yaw rate", "最大偏航角速度"),
        description=(
            "Yaw-rate limit for manual and autonomous modes except Acro.",
            "除 Acro 外手动和自主模式的偏航角速度限制。",
        ),
    ),
    _p(
        "MPC_XY_VEL_MAX",
        hard=(0.0, 20.0),
        safe=(1.0, 12.0),
        step=1.0,
        default=12.0,
        group="motion_limits",
        risk="medium",
        unit="m/s",
        label=("Maximum horizontal velocity", "最大水平速度"),
        description=(
            "Absolute velocity ceiling for horizontal controlled modes.",
            "水平速度控制模式的绝对速度上限。",
        ),
    ),
    _p(
        "MPC_Z_VEL_MAX_UP",
        hard=(0.5, 8.0),
        safe=(1.0, 5.0),
        step=0.1,
        default=3.0,
        group="motion_limits",
        risk="medium",
        unit="m/s",
        label=("Maximum ascent velocity", "最大上升速度"),
        description=("Absolute climb-rate ceiling.", "绝对上升速度上限。"),
    ),
    _p(
        "MPC_Z_VEL_MAX_DN",
        hard=(0.5, 4.0),
        safe=(0.5, 2.5),
        step=0.1,
        default=1.5,
        group="motion_limits",
        risk="medium",
        unit="m/s",
        label=("Maximum descent velocity", "最大下降速度"),
        description=("Absolute descent-rate ceiling.", "绝对下降速度上限。"),
    ),
    _p(
        "MPC_ACC_HOR",
        hard=(2.0, 15.0),
        safe=(2.0, 5.0),
        step=1.0,
        default=3.0,
        group="motion_limits",
        risk="medium",
        unit="m/s^2",
        label=("Horizontal acceleration", "水平加速度"),
        description=(
            "Commanded horizontal acceleration in autonomous modes.",
            "自主模式使用的水平加速度。",
        ),
        dependencies=(
            _dep(
                "less_than_or_equal",
                "MPC_ACC_HOR_MAX",
                "Must not exceed the maximum horizontal acceleration.",
                "不得超过最大水平加速度限制。",
            ),
        ),
    ),
    _p(
        "MPC_ACC_HOR_MAX",
        hard=(2.0, 15.0),
        safe=(5.0, 10.0),
        step=1.0,
        default=5.0,
        group="motion_limits",
        risk="medium",
        unit="m/s^2",
        label=("Maximum horizontal acceleration", "最大水平加速度"),
        description=(
            "Upper horizontal acceleration limit where applicable.",
            "适用模式下的水平加速度上限。",
        ),
    ),
    _p(
        "MPC_JERK_AUTO",
        hard=(1.0, 80.0),
        safe=(2.0, 20.0),
        step=1.0,
        default=4.0,
        group="motion_limits",
        risk="medium",
        unit="m/s^3",
        label=("Autonomous jerk limit", "自主模式加加速度限制"),
        description=(
            "Maximum acceleration slew in autonomous modes.",
            "自主模式中加速度变化率的上限。",
        ),
    ),
    _p(
        "MPC_TILTMAX_AIR",
        hard=(20.0, 89.0),
        safe=(25.0, 60.0),
        step=1.0,
        default=45.0,
        group="motion_limits",
        risk="high",
        unit="deg",
        label=("Maximum in-air tilt", "空中最大倾角"),
        description=(
            "Maximum tilt used by velocity and acceleration controlled flight modes.",
            "速度与加速度控制飞行模式允许的最大倾角。",
        ),
    ),
    _p(
        "MPC_TILTMAX_LND",
        hard=(5.0, 89.0),
        safe=(5.0, 20.0),
        step=1.0,
        default=12.0,
        group="motion_limits",
        risk="high",
        unit="deg",
        label=("Maximum takeoff-ramp tilt", "起飞坡道最大倾角"),
        description=(
            "Tighter tilt limit during the initial takeoff ramp to reduce tip-over risk.",
            "初始起飞坡道阶段使用的更严格倾角限制，用于降低倾覆风险。",
        ),
        dependencies=(
            _dep(
                "less_than_or_equal",
                "MPC_TILTMAX_AIR",
                "The takeoff tilt limit must not exceed the in-air limit.",
                "起飞倾角限制不得超过空中倾角限制。",
            ),
        ),
    ),
    _p(
        "MPC_THR_MIN",
        hard=(0.05, 0.5),
        safe=(0.08, 0.25),
        step=0.01,
        default=0.12,
        group="thrust_and_authority",
        risk="high",
        unit="norm",
        label=("Minimum collective thrust", "最小总推力"),
        description=(
            "Minimum thrust in climb-rate modes; too little can remove torque authority.",
            "升降速度模式的最小推力；过低可能导致力矩控制权丢失。",
        ),
        dependencies=(
            _dep(
                "less_than_or_equal",
                "MPC_THR_HOVER",
                "Minimum thrust must not exceed hover thrust.",
                "最小推力不得超过悬停推力。",
            ),
            _dep(
                "recommended_with",
                "MC_AIRMODE",
                "Minimum thrust and airmode jointly determine low-throttle authority.",
                "最小推力与 Air-mode 共同决定低油门控制权。",
            ),
        ),
    ),
    _p(
        "MPC_THR_HOVER",
        hard=(0.1, 0.8),
        safe=(0.25, 0.6),
        step=0.01,
        default=0.5,
        group="thrust_and_authority",
        risk="high",
        unit="norm",
        label=("Hover thrust", "悬停推力"),
        description=(
            "Vertical thrust needed to hover and the initial value for hover-thrust estimation.",
            "悬停所需的垂直推力，也是悬停推力估计器的初始值。",
        ),
        dependencies=(
            _dep(
                "less_than_or_equal",
                "MPC_THR_MAX",
                "Hover thrust must not exceed maximum collective thrust.",
                "悬停推力不得超过最大总推力。",
            ),
        ),
    ),
    _p(
        "MPC_THR_MAX",
        hard=(0.0, 1.0),
        safe=(0.6, 1.0),
        step=0.05,
        default=1.0,
        group="thrust_and_authority",
        risk="high",
        unit="norm",
        label=("Maximum collective thrust", "最大总推力"),
        description=(
            "Maximum allowed thrust in climb-rate controlled modes.",
            "升降速度控制模式允许的最大推力。",
        ),
    ),
    _p(
        "MPC_THR_XY_MARG",
        hard=(0.0, 0.5),
        safe=(0.1, 0.4),
        step=0.01,
        default=0.3,
        group="thrust_and_authority",
        risk="high",
        unit="norm",
        label=("Horizontal thrust margin", "水平推力余量"),
        description=(
            "Thrust reserved for horizontal control when vertical thrust saturates.",
            "垂直推力饱和时为水平控制保留的推力余量。",
        ),
    ),
    _p(
        "THR_MDL_FAC",
        hard=(0.0, 1.0),
        safe=(0.0, 0.7),
        step=0.1,
        default=0.0,
        group="thrust_and_authority",
        risk="high",
        unit="ratio",
        label=("Thrust model factor", "推力模型系数"),
        description=(
            "Models the nonlinear mapping from motor command to relative static thrust.",
            "描述电机指令到相对静态推力之间的非线性映射。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MPC_THR_HOVER",
                "Revalidate hover thrust and rate gains after changing the motor model.",
                "修改电机模型后应重新验证悬停推力与角速度增益。",
            ),
        ),
    ),
    _p(
        "MC_AIRMODE",
        hard=(0, 2),
        safe=(0, 2),
        step=1,
        default=0,
        group="thrust_and_authority",
        risk="high",
        value_type="int",
        choices=(
            (0, "Disabled", "禁用"),
            (1, "Roll/pitch", "横滚/俯仰"),
            (2, "Roll/pitch/yaw", "横滚/俯仰/偏航"),
        ),
        label=("Multicopter air-mode", "多旋翼 Air-mode"),
        description=(
            "Mixer control-authority policy at very low and high throttle (0, 1, or 2).",
            "极低或极高油门下的混控控制权策略（0、1 或 2）。",
        ),
    ),
    _p(
        "IMU_GYRO_CUTOFF",
        hard=(0.0, 1000.0),
        safe=(20.0, 80.0),
        step=1.0,
        default=40.0,
        group="filters",
        risk="high",
        unit="Hz",
        reboot=True,
        label=("Gyroscope low-pass cutoff", "陀螺仪低通截止频率"),
        description=(
            "Second-order low-pass cutoff for gyro data sent to the controllers.",
            "发送给控制器的陀螺仪数据二阶低通截止频率。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "MC_ROLLRATE_D",
                "Revalidate rate-loop D gains whenever gyro filtering changes.",
                "修改陀螺仪滤波后应重新验证角速度环 D 增益。",
            ),
        ),
    ),
    _p(
        "IMU_DGYRO_CUTOFF",
        hard=(0.0, 1000.0),
        safe=(10.0, 60.0),
        step=0.1,
        default=20.0,
        group="filters",
        risk="high",
        unit="Hz",
        reboot=True,
        label=("D-term low-pass cutoff", "D 项低通截止频率"),
        description=(
            "Low-pass cutoff for measured angular acceleration used by the rate D term.",
            "角速度环 D 项使用的测量角加速度低通截止频率。",
        ),
        dependencies=(
            _dep(
                "recommended_with",
                "IMU_GYRO_CUTOFF",
                "Validate gyro and D-term filters together against noise and latency.",
                "应结合噪声与延迟，联动验证陀螺仪和 D 项滤波。",
            ),
            _dep(
                "recommended_with",
                "MC_ROLLRATE_D",
                "Revalidate rate D gains after changing D-term filtering.",
                "修改 D 项滤波后应重新验证角速度 D 增益。",
            ),
        ),
    ),
)

TUNING_PRESETS: tuple[TuningPreset, ...] = (
    TuningPreset(
        id="rate_roll_pitch",
        order=10,
        label=_text("Roll and pitch rate", "横滚与俯仰角速度"),
        description=_text(
            "Tune the inner roll/pitch rate feedback loops before any outer loop.",
            "在任何外环之前先调节横滚/俯仰内层角速度反馈环。",
        ),
        parameter_names=(
            "MC_ROLLRATE_P",
            "MC_ROLLRATE_I",
            "MC_ROLLRATE_D",
            "MC_ROLLRATE_K",
            "MC_PITCHRATE_P",
            "MC_PITCHRATE_I",
            "MC_PITCHRATE_D",
            "MC_PITCHRATE_K",
        ),
        locked_parameters=("MC_ROLLRATE_K", "MC_PITCHRATE_K"),
        prerequisites=(
            "sitl_or_props_removed",
            "vehicle_stable",
            "high_rate_logging",
            "disable_airmode",
        ),
        scenario_types=("nominal", "noise_perturbed"),
        metrics=("rmse", "max_error", "overshoot_count", "instability_flag"),
        evidence_signals=(
            "vehicle_rates_setpoint",
            "vehicle_angular_velocity",
            "vehicle_torque_setpoint",
        ),
        expertise="advanced",
        recommended_iterations=24,
    ),
    TuningPreset(
        id="rate_yaw",
        order=20,
        label=_text("Yaw rate", "偏航角速度"),
        description=_text(
            "Tune yaw-rate tracking after roll and pitch are stable.",
            "横滚和俯仰稳定后再调节偏航角速度跟踪。",
        ),
        parameter_names=(
            "MC_YAWRATE_P",
            "MC_YAWRATE_I",
            "MC_YAWRATE_D",
            "MC_YAWRATE_K",
        ),
        locked_parameters=("MC_YAWRATE_D", "MC_YAWRATE_K"),
        prerequisites=("rate_loop_validated", "high_rate_logging"),
        scenario_types=("nominal", "noise_perturbed"),
        metrics=("rmse", "max_error", "overshoot_count", "instability_flag"),
        evidence_signals=(
            "vehicle_rates_setpoint",
            "vehicle_angular_velocity",
            "vehicle_torque_setpoint",
        ),
        expertise="advanced",
        recommended_iterations=16,
        follows=("rate_roll_pitch",),
    ),
    TuningPreset(
        id="attitude",
        order=30,
        label=_text("Attitude response", "姿态响应"),
        description=_text(
            "Tune attitude-error to body-rate gains after accepting all rate loops.",
            "验收全部角速度环后，再调节姿态误差到机体角速度的增益。",
        ),
        parameter_names=("MC_ROLL_P", "MC_PITCH_P", "MC_YAW_P"),
        prerequisites=("rate_loop_validated",),
        scenario_types=("nominal", "wind_perturbed"),
        metrics=("rmse", "max_error", "overshoot_count", "instability_flag"),
        evidence_signals=(
            "vehicle_attitude_setpoint",
            "vehicle_attitude",
            "vehicle_angular_velocity",
        ),
        expertise="guided",
        recommended_iterations=16,
        follows=("rate_roll_pitch", "rate_yaw"),
    ),
    TuningPreset(
        id="thrust_hover",
        order=40,
        label=_text("Hover thrust and authority", "悬停推力与控制权"),
        description=_text(
            "Calibrate hover thrust and thrust mapping before demanding position maneuvers.",
            "在执行高要求位置机动前，先校准悬停推力和推力映射。",
        ),
        parameter_names=(
            "MPC_THR_MIN",
            "MPC_THR_HOVER",
            "MPC_THR_MAX",
            "MPC_THR_XY_MARG",
            "THR_MDL_FAC",
            "MC_AIRMODE",
        ),
        locked_parameters=("MC_AIRMODE",),
        prerequisites=("rate_loop_validated",),
        scenario_types=("nominal", "wind_perturbed"),
        metrics=("rmse", "max_error", "final_error", "instability_flag"),
        evidence_signals=(
            "vehicle_thrust_setpoint",
            "actuator_motors",
            "vehicle_local_position",
        ),
        expertise="advanced",
        recommended_iterations=20,
        follows=("rate_roll_pitch",),
    ),
    TuningPreset(
        id="position_xy",
        order=50,
        label=_text("Horizontal position and velocity", "水平位置与速度"),
        description=_text(
            "Tune horizontal velocity first, then the outer position gain.",
            "先调节水平速度环，再调节外层位置增益。",
        ),
        parameter_names=(
            "MPC_XY_VEL_P_ACC",
            "MPC_XY_VEL_I_ACC",
            "MPC_XY_VEL_D_ACC",
            "MPC_XY_P",
        ),
        prerequisites=("attitude_loop_validated",),
        scenario_types=("nominal", "wind_perturbed", "combined_perturbed"),
        metrics=("rmse", "max_error", "overshoot_count", "completion_time"),
        evidence_signals=("trajectory_setpoint", "vehicle_local_position"),
        expertise="guided",
        recommended_iterations=24,
        follows=("attitude", "thrust_hover"),
    ),
    TuningPreset(
        id="position_z",
        order=60,
        label=_text("Vertical position and velocity", "垂直位置与速度"),
        description=_text(
            "Tune climb-rate response before the outer altitude position gain.",
            "先调节升降速度响应，再调节外层高度位置增益。",
        ),
        parameter_names=(
            "MPC_Z_VEL_P_ACC",
            "MPC_Z_VEL_I_ACC",
            "MPC_Z_VEL_D_ACC",
            "MPC_Z_P",
        ),
        prerequisites=("attitude_loop_validated",),
        scenario_types=("nominal", "wind_perturbed", "combined_perturbed"),
        metrics=("rmse", "max_error", "overshoot_count", "completion_time"),
        evidence_signals=("trajectory_setpoint", "vehicle_local_position"),
        expertise="guided",
        recommended_iterations=20,
        follows=("attitude", "thrust_hover"),
    ),
    TuningPreset(
        id="motion_envelope",
        order=70,
        label=_text("Motion envelope", "运动包线"),
        description=_text(
            "Optimize speed, acceleration, jerk, and tilt limits after the tracking loops.",
            "跟踪控制环稳定后，再优化速度、加速度、加加速度和倾角限制。",
        ),
        parameter_names=(
            "MPC_XY_VEL_MAX",
            "MPC_Z_VEL_MAX_UP",
            "MPC_Z_VEL_MAX_DN",
            "MPC_ACC_HOR",
            "MPC_ACC_HOR_MAX",
            "MPC_JERK_AUTO",
            "MPC_TILTMAX_AIR",
            "MPC_TILTMAX_LND",
        ),
        prerequisites=("attitude_loop_validated",),
        scenario_types=("nominal", "wind_perturbed", "combined_perturbed"),
        metrics=("rmse", "max_error", "completion_time", "instability_flag"),
        evidence_signals=(
            "trajectory_setpoint",
            "vehicle_local_position",
            "control_allocator_status",
        ),
        expertise="advanced",
        recommended_iterations=24,
        follows=("position_xy", "position_z"),
    ),
    TuningPreset(
        id="filters_expert",
        order=80,
        label=_text("Controller filters", "控制器滤波"),
        description=_text(
            "Expert-only noise/latency trade-off using high-rate gyro evidence.",
            "仅限专家：使用高频陀螺仪证据权衡噪声与延迟。",
        ),
        parameter_names=("IMU_GYRO_CUTOFF", "IMU_DGYRO_CUTOFF"),
        prerequisites=("rate_loop_validated", "high_rate_logging"),
        scenario_types=("nominal", "noise_perturbed"),
        metrics=("rmse", "overshoot_count", "instability_flag"),
        evidence_signals=(
            "sensor_gyro",
            "vehicle_angular_velocity",
            "vehicle_angular_acceleration",
        ),
        expertise="expert",
        recommended_iterations=16,
        follows=("rate_roll_pitch",),
    ),
)

_BY_NAME = {parameter.name: parameter for parameter in PARAMETERS}
_GROUP_IDS = {str(item["id"]) for item in GROUPS}
_PRESET_BY_ID = {preset.id: preset for preset in TUNING_PRESETS}


def _source_url_for(px4_version: str, parameter_name: str | None = None) -> str:
    base = (
        "https://docs.px4.io/"
        f"{px4_version}/en/advanced_config/parameter_reference"
    )
    return f"{base}#{parameter_name}" if parameter_name else base


def _definition_for_version(
    parameter: ParameterDefinition,
    px4_version: str,
) -> ParameterDefinition:
    """Apply audited release-specific metadata without mutating the registry."""

    effective = replace(
        parameter,
        source_url=_source_url_for(px4_version, parameter.name),
    )
    if parameter.name == "IMU_DGYRO_CUTOFF" and px4_version in {"v1.16", "v1.17"}:
        effective = replace(effective, default=30.0)
    if parameter.name == "MC_YAWRATE_K" and px4_version in {"v1.16", "v1.17"}:
        effective = replace(effective, hard_bounds=Bounds(0.0, 5.0))
    if parameter.name == "MC_YAWRATE_D" and px4_version in {"v1.16", "v1.17"}:
        effective = replace(
            effective,
            safe_bounds=Bounds(0.0, 0.01),
            step=0.01,
        )
    return effective


def resolve_catalog_version(value: str | None, *, px4_version: str | None = None) -> str:
    """Resolve only explicit catalog identifiers and guard version-specific aliases."""

    raw = CATALOG_VERSION if value is None else value.strip()
    if not raw:
        raise ValueError("Parameter catalog version cannot be blank")
    key = raw.lower()
    if key == CATALOG_VERSION.lower():
        return CATALOG_VERSION
    resolved = CATALOG_VERSION_ALIASES.get(key)
    if resolved is None:
        accepted = ", ".join((CATALOG_VERSION, *CATALOG_VERSION_ALIASES))
        raise ValueError(f"Unsupported parameter catalog {value!r}; accepted values: {accepted}")
    if key.startswith("px4-") and px4_version is not None:
        normalized_px4 = normalize_px4_version(px4_version)
        alias_px4 = key.removeprefix("px4-")
        if alias_px4 != normalized_px4:
            raise ValueError(
                f"Parameter catalog {raw!r} targets {alias_px4}, not requested PX4 {normalized_px4}"
            )
    return resolved


def normalize_px4_version(value: str | None) -> str:
    """Normalize supported release spellings without silently crossing versions."""

    raw = (value or "main").strip().lower()
    if raw == "main":
        return "main"
    match = re.fullmatch(r"v?(1\.(?:16|17))(?:\.\d+)?", raw)
    if match:
        return f"v{match.group(1)}"
    supported = ", ".join(SUPPORTED_PX4_VERSIONS)
    raise ValueError(f"Unsupported PX4 version {value!r}; supported versions: {supported}")


def normalize_vehicle_type(value: str | None) -> str:
    """Normalize supported multicopter spellings and reject unrelated controllers."""

    raw = (value or "multicopter").strip().lower().replace("-", "_")
    aliases = {
        "mc": "multicopter",
        "multirotor": "multicopter",
        "multi_rotor": "multicopter",
        "quadrotor": "multicopter",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in SUPPORTED_VEHICLE_TYPES:
        supported = ", ".join(SUPPORTED_VEHICLE_TYPES)
        raise ValueError(
            f"Unsupported vehicle type {value!r} for this catalog; supported: {supported}"
        )
    return normalized


def classify_airframe(value: str | None) -> str:
    """Map a PX4/Gazebo airframe identifier to a compatibility family."""

    raw = "x500" if value is None else value.strip().lower()
    if not raw:
        raise ValueError("airframe cannot be blank")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", raw):
        raise ValueError("airframe must contain only letters, digits, dot, underscore, or dash")
    if "hexa" in raw or "h480" in raw:
        return "hexarotor"
    if "octo" in raw:
        return "octocopter"
    if any(token in raw for token in ("x500", "quad", "iris")):
        return "quadrotor"
    return "custom_multicopter"


def _catalog_context(
    *,
    px4_version: str | None,
    vehicle_type: str | None,
    airframe: str | None,
) -> tuple[str, str, str]:
    return (
        normalize_px4_version(px4_version),
        normalize_vehicle_type(vehicle_type),
        classify_airframe(airframe),
    )


def get_parameter(
    name: str,
    *,
    px4_version: str | None = None,
    vehicle_type: str | None = None,
    airframe: str | None = None,
) -> ParameterDefinition | None:
    version, normalized_vehicle, family = _catalog_context(
        px4_version=px4_version,
        vehicle_type=vehicle_type,
        airframe=airframe,
    )
    parameter = _BY_NAME.get(name.strip().upper())
    if parameter is None:
        return None
    if not parameter.compatibility.supports(
        px4_version=version,
        vehicle_type=normalized_vehicle,
        airframe_family=family,
    ):
        return None
    return _definition_for_version(parameter, version)


def list_parameters(
    *,
    px4_version: str | None = None,
    vehicle_type: str | None = None,
    airframe: str | None = None,
    group: str | None = None,
    control_loop: str | None = None,
    axis: str | None = None,
    risk: ParameterRisk | None = None,
) -> tuple[ParameterDefinition, ...]:
    version, normalized_vehicle, family = _catalog_context(
        px4_version=px4_version,
        vehicle_type=vehicle_type,
        airframe=airframe,
    )
    if group is not None and group not in _GROUP_IDS:
        raise ValueError(f"Unknown parameter group: {group}")
    known_loops = {parameter.control_loop for parameter in PARAMETERS}
    if control_loop is not None and control_loop not in known_loops:
        raise ValueError(f"Unknown control loop: {control_loop}")
    known_axes = {axis_name for parameter in PARAMETERS for axis_name in parameter.axes}
    if axis is not None and axis not in known_axes and axis != "xy":
        raise ValueError(f"Unknown parameter axis: {axis}")
    if risk is not None and risk not in {"low", "medium", "high"}:
        raise ValueError(f"Unknown parameter risk: {risk}")

    def included(parameter: ParameterDefinition) -> bool:
        compatible = parameter.compatibility.supports(
            px4_version=version,
            vehicle_type=normalized_vehicle,
            airframe_family=family,
        )
        axis_matches = (
            axis is None
            or axis in parameter.axes
            or (axis == "xy" and "x" in parameter.axes and "y" in parameter.axes)
        )
        return (
            compatible
            and (group is None or parameter.group == group)
            and (control_loop is None or parameter.control_loop == control_loop)
            and axis_matches
            and (risk is None or parameter.risk == risk)
        )

    return tuple(
        _definition_for_version(parameter, version)
        for parameter in PARAMETERS
        if included(parameter)
    )


def list_presets(
    *,
    px4_version: str | None = None,
    vehicle_type: str | None = None,
    airframe: str | None = None,
) -> tuple[TuningPreset, ...]:
    available = {
        parameter.name
        for parameter in list_parameters(
            px4_version=px4_version,
            vehicle_type=vehicle_type,
            airframe=airframe,
        )
    }
    return tuple(
        preset for preset in TUNING_PRESETS if set(preset.parameter_names).issubset(available)
    )


def preset_payload(
    *,
    px4_version: str | None = None,
    vehicle_type: str | None = None,
    airframe: str | None = None,
) -> dict[str, object]:
    version, normalized_vehicle, family = _catalog_context(
        px4_version=px4_version,
        vehicle_type=vehicle_type,
        airframe=airframe,
    )
    presets = list_presets(
        px4_version=version,
        vehicle_type=normalized_vehicle,
        airframe=airframe,
    )
    return {
        "catalog_version": CATALOG_VERSION,
        "px4_version": version,
        "vehicle_type": normalized_vehicle,
        "airframe": airframe or "x500",
        "airframe_family": family,
        "preconditions": list(WORKFLOW_PRECONDITIONS),
        "supported_trial_metrics": list(SUPPORTED_TRIAL_METRICS),
        "preset_count": len(presets),
        "presets": [preset.to_dict() for preset in presets],
    }


def catalog_payload(
    *,
    px4_version: str | None = None,
    vehicle_type: str | None = None,
    airframe: str | None = None,
    group: str | None = None,
    control_loop: str | None = None,
    axis: str | None = None,
    risk: ParameterRisk | None = None,
) -> dict[str, object]:
    normalized_version, normalized_vehicle, family = _catalog_context(
        px4_version=px4_version,
        vehicle_type=vehicle_type,
        airframe=airframe,
    )
    parameters = list_parameters(
        px4_version=normalized_version,
        vehicle_type=normalized_vehicle,
        airframe=airframe,
        group=group,
        control_loop=control_loop,
        axis=axis,
        risk=risk,
    )
    included_group_ids = {parameter.group for parameter in parameters}
    presets = list_presets(
        px4_version=normalized_version,
        vehicle_type=normalized_vehicle,
        airframe=airframe,
    )
    visible_names = {parameter.name for parameter in parameters}
    if any(value is not None for value in (group, control_loop, axis, risk)):
        presets = tuple(
            preset for preset in presets if set(preset.parameter_names).issubset(visible_names)
        )
    return {
        "catalog_version": CATALOG_VERSION,
        "catalog_version_aliases": list(CATALOG_VERSION_ALIASES),
        "source": CATALOG_SOURCE,
        "source_url": _source_url_for(normalized_version),
        "px4_version": normalized_version,
        "supported_px4_versions": list(SUPPORTED_PX4_VERSIONS),
        "vehicle_type": normalized_vehicle,
        "supported_vehicle_types": list(SUPPORTED_VEHICLE_TYPES),
        "airframe": airframe or "x500",
        "airframe_family": family,
        "supported_airframe_families": list(SUPPORTED_AIRFRAME_FAMILIES),
        "application_interfaces": ["mavsdk", "px4_startup_env"],
        "supported_trial_metrics": list(SUPPORTED_TRIAL_METRICS),
        "total_parameter_count": len(
            list_parameters(
                px4_version=normalized_version,
                vehicle_type=normalized_vehicle,
                airframe=airframe,
            )
        ),
        "parameter_count": len(parameters),
        "tuning_order": [
            "angular_rate",
            "attitude",
            "thrust_and_authority",
            "filters",
            "xy_position_velocity",
            "z_position_velocity",
            "motion_limits",
        ],
        "preconditions": list(WORKFLOW_PRECONDITIONS),
        "presets": [preset.to_dict() for preset in presets],
        "groups": [item for item in GROUPS if item["id"] in included_group_ids],
        "parameters": [parameter.to_dict() for parameter in parameters],
    }


def _validate_catalog_integrity() -> None:
    group_orders = [cast(int, item["order"]) for item in GROUPS]
    if len(_GROUP_IDS) != len(GROUPS) or group_orders != sorted(set(group_orders)):
        raise RuntimeError("PX4 parameter groups require unique ids and ascending orders")
    precondition_ids = {str(item["id"]) for item in WORKFLOW_PRECONDITIONS}
    if len(precondition_ids) != len(WORKFLOW_PRECONDITIONS):
        raise RuntimeError("PX4 workflow preconditions contain duplicate ids")
    if len(_BY_NAME) != len(PARAMETERS):
        raise RuntimeError("PX4 parameter catalog contains duplicate names")
    for parameter in PARAMETERS:
        if parameter.group not in _GROUP_IDS:
            raise RuntimeError(f"{parameter.name} references unknown group {parameter.group}")
        hard = parameter.hard_bounds
        safe = parameter.safe_bounds
        if hard.minimum > safe.minimum or safe.maximum > hard.maximum:
            raise RuntimeError(f"{parameter.name} safe bounds escape hard bounds")
        if not safe.contains(parameter.default):
            raise RuntimeError(f"{parameter.name} default is outside safe bounds")
        if float(parameter.step) <= 0 or not re.fullmatch(r"[A-Z][A-Z0-9_]+", parameter.name):
            raise RuntimeError(f"{parameter.name} has invalid name or step")
        if parameter.value_type == "int" and any(
            not float(value).is_integer()
            for value in (
                hard.minimum,
                hard.maximum,
                safe.minimum,
                safe.maximum,
                parameter.step,
                parameter.default,
            )
        ):
            raise RuntimeError(f"{parameter.name} integer metadata contains a fractional value")
        choice_values = [choice.value for choice in parameter.choices]
        if len(set(choice_values)) != len(choice_values):
            raise RuntimeError(f"{parameter.name} contains duplicate choices")
        if parameter.choices and parameter.value_type != "int":
            raise RuntimeError(f"{parameter.name} choices require an integer parameter")
        if any(
            not parameter.hard_bounds.contains(choice) or not float(choice).is_integer()
            for choice in choice_values
        ):
            raise RuntimeError(f"{parameter.name} contains an invalid catalog choice")
        if parameter.requires_reboot != (parameter.apply_policy == "reboot"):
            raise RuntimeError(f"{parameter.name} has inconsistent reboot/apply metadata")
        if not set(parameter.application_interfaces).issubset(
            {"mavsdk", "px4_startup_env"}
        ):
            raise RuntimeError(f"{parameter.name} has an unsupported application interface")
        if not set(parameter.recommended_metrics).issubset(SUPPORTED_TRIAL_METRICS):
            raise RuntimeError(f"{parameter.name} recommends unsupported trial metrics")
        if not parameter.evidence_signals:
            raise RuntimeError(f"{parameter.name} requires at least one evidence signal")
        unknown_preconditions = set(parameter.preconditions) - precondition_ids
        if unknown_preconditions:
            raise RuntimeError(
                f"{parameter.name} references unknown preconditions: "
                f"{sorted(unknown_preconditions)}"
            )
        for dependency in parameter.dependencies:
            if dependency.parameter not in _BY_NAME:
                raise RuntimeError(
                    f"{parameter.name} references unknown dependency {dependency.parameter}"
                )
        for px4_version in parameter.compatibility.px4_versions:
            effective = _definition_for_version(parameter, px4_version)
            if (
                effective.hard_bounds.minimum > effective.safe_bounds.minimum
                or effective.safe_bounds.maximum > effective.hard_bounds.maximum
                or not effective.safe_bounds.contains(effective.default)
            ):
                raise RuntimeError(
                    f"{parameter.name} has inconsistent metadata for {px4_version}"
                )
    if len(_PRESET_BY_ID) != len(TUNING_PRESETS):
        raise RuntimeError("PX4 tuning presets contain duplicate ids")
    for preset in TUNING_PRESETS:
        unknown = set(preset.parameter_names) - _BY_NAME.keys()
        if unknown:
            raise RuntimeError(f"{preset.id} references unknown parameters: {sorted(unknown)}")
        unknown_follows = set(preset.follows) - _PRESET_BY_ID.keys()
        if unknown_follows:
            raise RuntimeError(f"{preset.id} follows unknown presets: {sorted(unknown_follows)}")
        if not set(preset.locked_parameters).issubset(preset.parameter_names):
            raise RuntimeError(f"{preset.id} locks parameters outside the preset")
        if not set(preset.metrics).issubset(SUPPORTED_TRIAL_METRICS):
            raise RuntimeError(f"{preset.id} recommends unsupported trial metrics")
        if not preset.evidence_signals:
            raise RuntimeError(f"{preset.id} requires at least one evidence signal")
        unknown_preconditions = set(preset.prerequisites) - precondition_ids
        if unknown_preconditions:
            raise RuntimeError(
                f"{preset.id} references unknown preconditions: {sorted(unknown_preconditions)}"
            )
        if any(_PRESET_BY_ID[parent].order >= preset.order for parent in preset.follows):
            raise RuntimeError(f"{preset.id} must follow only earlier workflow stages")


_validate_catalog_integrity()
