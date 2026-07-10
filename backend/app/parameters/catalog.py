"""Curated, versioned catalog of multicopter PX4 tuning parameters.

Hard bounds follow the PX4 parameter reference where it declares finite limits.
For gains where upstream has no finite maximum, DroneDream deliberately supplies
a conservative finite guardrail. Safe bounds are narrower DroneDream defaults;
they are not claims about safe values for every physical airframe.
"""

from __future__ import annotations

import re
from typing import Literal

from app.parameters.models import (
    Bounds,
    LocalizedText,
    Number,
    ParameterDefinition,
    ParameterDependency,
    ParameterRisk,
    ParameterValueType,
)

CATALOG_VERSION = "dronedream.px4.multicopter.2026-07-r1"
CATALOG_SOURCE = "PX4 main parameter reference snapshot 2026-07-10"
SUPPORTED_PX4_VERSIONS = ("v1.16", "v1.17", "main")

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
        "id": "filters",
        "order": 45,
        "label": {"en": "Controller filters", "zh-CN": "控制器滤波"},
        "description": {
            "en": "Gyroscope and D-term filtering that trades noise against latency.",
            "zh-CN": "在噪声抑制与控制延迟之间权衡的陀螺仪与 D 项滤波。",
        },
    },
    {
        "id": "motion_limits",
        "order": 50,
        "label": {"en": "Motion limits", "zh-CN": "运动限制"},
        "description": {
            "en": "Velocity, acceleration, and jerk limits used by position control.",
            "zh-CN": "位置控制使用的速度、加速度与加加速度限制。",
        },
    },
)


def _text(en: str, zh_cn: str) -> LocalizedText:
    return LocalizedText(en=en, zh_cn=zh_cn)


def _dep(
    kind: Literal["recommended_with", "less_than_or_equal"],
    parameter: str,
    en: str,
    zh_cn: str,
) -> ParameterDependency:
    return ParameterDependency(
        kind=kind,
        parameter=parameter,
        description=_text(en, zh_cn),
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
) -> ParameterDefinition:
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
        default=4.0,
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
        default=4.0,
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
        safe=(2.0, 8.0),
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
        safe=(3.0, 10.0),
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
        "MC_AIRMODE",
        hard=(0, 2),
        safe=(0, 2),
        step=1,
        default=0,
        group="motion_limits",
        risk="high",
        value_type="int",
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
)

_BY_NAME = {parameter.name: parameter for parameter in PARAMETERS}


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


def get_parameter(name: str, *, px4_version: str | None = None) -> ParameterDefinition | None:
    normalize_px4_version(px4_version)
    return _BY_NAME.get(name.strip().upper())


def list_parameters(
    *, px4_version: str | None = None, group: str | None = None
) -> tuple[ParameterDefinition, ...]:
    normalize_px4_version(px4_version)
    if group is None:
        return PARAMETERS
    known_groups = {str(item["id"]) for item in GROUPS}
    if group not in known_groups:
        raise ValueError(f"Unknown parameter group: {group}")
    return tuple(parameter for parameter in PARAMETERS if parameter.group == group)


def catalog_payload(
    *, px4_version: str | None = None, group: str | None = None
) -> dict[str, object]:
    normalized_version = normalize_px4_version(px4_version)
    parameters = list_parameters(px4_version=normalized_version, group=group)
    included_group_ids = {parameter.group for parameter in parameters}
    return {
        "catalog_version": CATALOG_VERSION,
        "source": CATALOG_SOURCE,
        "px4_version": normalized_version,
        "supported_px4_versions": list(SUPPORTED_PX4_VERSIONS),
        "vehicle_type": "multicopter",
        "parameter_count": len(parameters),
        "tuning_order": [
            "angular_rate",
            "attitude",
            "filters",
            "xy_position_velocity",
            "z_position_velocity",
            "motion_limits",
        ],
        "groups": [item for item in GROUPS if item["id"] in included_group_ids],
        "parameters": [parameter.to_dict() for parameter in parameters],
    }
