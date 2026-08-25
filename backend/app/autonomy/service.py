"""Bounded natural-language compiler, trajectory checks, and edition policy."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from app.autonomy.catalog import SCENES, get_scene
from app.autonomy.models import (
    AutonomyCompileRequest,
    AutonomyCompileResponse,
    ExecutionAdapter,
    ExecutionPolicy,
    MissionAction,
    MissionContract,
    MissionMetrics,
    MissionStep,
    MissionTaskGraph,
    MissionTaskNode,
    OnboardRuntimeProfile,
    PerceptionMode,
    RoutePoint,
    RuntimeBridge,
    RuntimeComponent,
    RuntimeComponentId,
    RuntimeComponentStatus,
    RuntimeMode,
    SafetyAction,
    TaskExecutor,
    TaskNodeStatus,
    TaskRisk,
    ValidationIssue,
)
from app.autonomy.school_map_artifact import (
    OFFICE_DOOR_CENTER_X,
    TEACHING_OPEN_DOOR_PAIR_CENTER_X,
    school_map_stair_route_points,
)

GRAVITY = 9.80665
MIN_THRUST_TO_WEIGHT = 1.35
MASS_COMPARISON_TOLERANCE_KG = 1e-9
VALIDATED_SIGNED_PACK_COUNT = 0
SchoolMissionProfile = Literal["coffee", "gates", "narrow"]


class AutonomyCompileError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _localized(locale: Literal["en", "zh-CN"], english: str, chinese: str) -> str:
    """Select independently authored display text while keeping protocol IDs stable."""

    return chinese if locale == "zh-CN" else english


def runtime_profile_for(request: AutonomyCompileRequest) -> OnboardRuntimeProfile:
    """Describe the runtime boundary without claiming that hardware is connected."""

    if request.execution_target == "simulation":
        mode: RuntimeMode = "simulation_contract"
        bridge: RuntimeBridge = "px4_gazebo"
        status: RuntimeComponentStatus = "available"
        authority = True
    elif request.execution_target == "hitl":
        mode = "hitl_shadow"
        bridge = "px4_hitl_shadow"
        status = "shadow"
        authority = False
    else:
        mode = "hardware_locked"
        bridge = "px4_hardware_locked"
        status = "locked"
        authority = False

    localization_role = (
        _localized(
            request.locale,
            (
                "Consumes the qualified School Map and PX4 Gazebo GPS state; no camera or "
                "VIO stream is attached to the official vehicle."
            ),
            "读取已验证的 School Map 与 PX4 Gazebo GPS 状态；正式机型未接入相机或 VIO 数据流。",
        )
        if request.perception_mode == "map"
        else _localized(
            request.locale,
            "Accepts versioned VIO, SLAM, map and vision observations.",
            "接收带版本标识的 VIO、SLAM、地图和视觉观测。",
        )
    )
    localization_rate_hz = 10.0 if request.perception_mode == "map" else 30.0
    component_specs: tuple[tuple[RuntimeComponentId, str, float], ...] = (
        (
            "mission_executive",
            _localized(
                request.locale,
                "Runs the bounded mission state machine.",
                "运行有边界的任务状态机。",
            ),
            20.0,
        ),
        ("perception_vio_slam", localization_role, localization_rate_hz),
        (
            "world_model",
            _localized(
                request.locale,
                "Maintains obstacle, gate, terrain and payload state.",
                "维护障碍物、门、地形和载荷状态。",
            ),
            20.0,
        ),
        (
            "global_planner",
            _localized(
                request.locale,
                "Builds the route corridor between mission checkpoints.",
                "生成任务检查点之间的全局路线走廊。",
            ),
            2.0,
        ),
        (
            "local_planner",
            _localized(
                request.locale,
                "Repairs the trajectory inside the approved corridor.",
                "在已批准的走廊内修复局部航迹。",
            ),
            20.0,
        ),
        (
            "trajectory_tracker",
            _localized(
                request.locale,
                "Converts a qualified trajectory to PX4 setpoint contracts.",
                "把已验证航迹转换为 PX4 设定点合同。",
            ),
            20.0,
        ),
        (
            "px4_bridge",
            _localized(
                request.locale,
                "Separates simulator, HITL shadow and locked aircraft transports.",
                "隔离仿真、HITL 影子模式与锁定真机的传输通道。",
            ),
            20.0,
        ),
        (
            "safety_supervisor",
            _localized(
                request.locale,
                "Checks live clearance and overrides with abort decisions.",
                "实时检查净空，并在必要时覆盖为中止决策。",
            ),
            5.0,
        ),
        (
            "evidence_recorder",
            _localized(
                request.locale,
                "Hash-chains accepted observations and decisions.",
                "将已接受的观测与决策写入哈希证据链。",
            ),
            20.0,
        ),
    )
    components = [
        RuntimeComponent(
            id=component_id,
            status=status,
            role=role,
            rate_hz=rate_hz,
            actuator_authority=authority and component_id == "px4_bridge",
        )
        for component_id, role, rate_hz in component_specs
    ]
    return OnboardRuntimeProfile(
        mode=mode,
        bridge=bridge,
        command_authority=authority,
        components=components,
        fail_safe_actions=["hold", "land", "abort"],
    )


def _select_scene(request: AutonomyCompileRequest) -> str:
    if request.scene_id:
        if request.scene_id not in SCENES:
            raise AutonomyCompileError(
                "UNKNOWN_AUTONOMY_SCENE",
                _localized(
                    request.locale,
                    "The requested terrain scene is not registered.",
                    "所请求的地形场景尚未注册。",
                ),
                404,
            )
        return request.scene_id
    text = request.natural_language.casefold()
    if any(token in text for token in ("gate", "圆门", "穿门", "树林", "forest")):
        return "forest-gate-inspection"
    if any(token in text for token in ("dock", "走廊", "corridor", "停靠", "狭窄")):
        return "service-corridor-dock"
    return "school-campus-v1"


def _select_perception(request: AutonomyCompileRequest) -> PerceptionMode:
    if request.perception_mode:
        return request.perception_mode
    text = request.natural_language.casefold()
    mentions_map = any(token in text for token in ("map", "地图", "occupancy"))
    mentions_vision = any(
        token in text for token in ("camera", "vision", "摄像", "视觉", "rgb", "depth")
    )
    if mentions_map and mentions_vision:
        return "fusion"
    if mentions_vision:
        return "vision"
    if mentions_map:
        return "map"
    return "fusion"


def school_mission_profile(
    request: AutonomyCompileRequest,
    scene_id: str,
) -> SchoolMissionProfile:
    """Select a deterministic route contract inside the shared School Map.

    Public mission presets now share one physical scene. Intent classification
    therefore selects a route and task graph, not a different display-only map.
    Explicit legacy scene identifiers remain stable for existing API clients.
    """

    if scene_id == "forest-gate-inspection":
        return "gates"
    if scene_id == "service-corridor-dock":
        return "narrow"
    if scene_id == "stairwell-coffee-return":
        return "coffee"

    text = request.natural_language.casefold()
    if any(token in text for token in ("gate", "ring", "圆门", "圆环", "穿门")):
        return "gates"
    if any(
        token in text
        for token in (
            "narrow",
            "corridor",
            "stair",
            "狭窄",
            "走廊",
            "楼梯",
            "通道",
        )
    ):
        return "narrow"
    if any(
        token in text
        for token in (
            "coffee",
            "pickup",
            "pick up",
            "takeout",
            "return",
            "咖啡",
            "取餐",
            "外卖",
            "取回",
            "返航",
        )
    ):
        return "coffee"
    return "coffee"


def _steps(
    scene_id: str,
    profile: SchoolMissionProfile,
    pickup_payload_kg: float,
    locale: Literal["en", "zh-CN"],
) -> list[MissionStep]:
    if scene_id == "forest-gate-inspection":
        return [
            MissionStep(
                order=1,
                action="takeoff",
                label=_localized(locale, "Launch into the vegetation corridor", "起飞进入植被走廊"),
            ),
            MissionStep(
                order=2,
                action="pass_gate",
                label=_localized(
                    locale,
                    "Pass three gates through their geometric centers",
                    "依次从三座训练门的几何中心穿过",
                ),
            ),
            MissionStep(
                order=3,
                action="land",
                label=_localized(
                    locale, "Complete the inspection hover and land", "完成巡检悬停并降落"
                ),
            ),
        ]
    if scene_id == "service-corridor-dock":
        return [
            MissionStep(
                order=1,
                action="takeoff",
                label=_localized(locale, "Launch in the service corridor", "在服务走廊内起飞"),
            ),
            MissionStep(
                order=2,
                action="transit",
                label=_localized(
                    locale,
                    "Follow the narrow collision-free corridor around blind corners",
                    "沿无碰撞的狭窄走廊通过盲角",
                ),
            ),
            MissionStep(
                order=3,
                action="land",
                label=_localized(locale, "Dock on the marked target", "在标记目标上精准降落"),
            ),
        ]
    if profile == "coffee":
        return [
            MissionStep(
                order=1,
                action="takeoff",
                label=_localized(locale, "Launch from the third-floor office", "从三楼办公室起飞"),
            ),
            MissionStep(
                order=2,
                action="traverse_stairs",
                label=_localized(
                    locale,
                    "Descend the narrow stairwell through two landings",
                    "穿过两个楼梯平台，下行狭窄楼梯间",
                ),
            ),
            MissionStep(
                order=3,
                action="transit",
                label=_localized(
                    locale,
                    "Exit to the courtyard and avoid trees, signs, poles and buildings",
                    "飞出教学楼进入庭院，避开树木、标牌、立柱和建筑物",
                ),
            ),
            MissionStep(
                order=4,
                action="pickup",
                label=_localized(
                    locale, "Acquire the coffee at the docking target", "在取货目标点拿取咖啡"
                ),
                payload_delta_kg=pickup_payload_kg,
            ),
            MissionStep(
                order=5,
                action="return",
                label=_localized(
                    locale,
                    "Replan with the loaded vehicle envelope and return upstairs",
                    "根据载荷后的飞行包络重新规划并返回楼上",
                ),
            ),
            MissionStep(
                order=6,
                action="land",
                label=_localized(locale, "Land at the original launch point", "在原起飞点降落"),
            ),
        ]
    if profile == "gates":
        return [
            MissionStep(
                order=1,
                action="takeoff",
                label=_localized(
                    locale, "Launch onto the campus gate course", "起飞进入校园训练门路线"
                ),
            ),
            MissionStep(
                order=2,
                action="pass_gate",
                label=_localized(
                    locale,
                    "Pass the three training gates through their geometric centers",
                    "依次从三座训练门的几何中心穿过",
                ),
            ),
            MissionStep(
                order=3,
                action="land",
                label=_localized(locale, "Land at the east course goal", "在训练路线东侧终点降落"),
            ),
        ]
    return [
        MissionStep(
            order=1,
            action="takeoff",
            label=_localized(locale, "Launch from the third-floor office", "从三楼办公室起飞"),
        ),
        MissionStep(
            order=2,
            action="traverse_stairs",
            label=_localized(
                locale,
                "Traverse the teaching wing and descend both switchback stair flights",
                "穿过教学楼并下行两段折返楼梯",
            ),
        ),
        MissionStep(
            order=3,
            action="land",
            label=_localized(locale, "Land outside the teaching entrance", "在教学楼入口外降落"),
        ),
    ]


def _school_reference_path(profile: SchoolMissionProfile) -> list[RoutePoint] | None:
    """Return School Map paths in the backend ENU vector convention.

    Three.js renders `(east, altitude, north)` while the API stores
    `(east, north, altitude)`, so every reviewed visual waypoint is explicitly
    transposed here instead of being inferred at runtime.
    """

    if profile == "coffee":
        return None
    if profile == "gates":
        return [
            RoutePoint(x=-24.8, y=-1.055, z=1.4, phase="launch", speed_limit_mps=0.7),
            RoutePoint(x=-25.0, y=-9.0, z=1.7, phase="transit", speed_limit_mps=0.9),
            RoutePoint(x=-25.0, y=-18.0, z=1.9, phase="transit", speed_limit_mps=1.0),
            RoutePoint(x=-13.0, y=-18.0, z=2.2, phase="transit", speed_limit_mps=1.1),
            RoutePoint(x=-5.0, y=-18.0, z=2.4, phase="gate", speed_limit_mps=0.8),
            RoutePoint(x=5.0, y=-18.0, z=2.2, phase="transit", speed_limit_mps=1.0),
            RoutePoint(x=15.0, y=-18.0, z=2.5, phase="gate", speed_limit_mps=0.8),
            RoutePoint(x=25.0, y=-18.0, z=2.2, phase="transit", speed_limit_mps=1.0),
            RoutePoint(x=35.0, y=-18.0, z=1.9, phase="gate", speed_limit_mps=0.8),
            RoutePoint(x=48.0, y=-18.0, z=1.3, phase="land", speed_limit_mps=0.4),
        ]
    return [
        RoutePoint(x=-42.25, y=15.3, z=8.15, phase="launch", speed_limit_mps=0.55),
        RoutePoint(x=-42.25, y=11.5, z=8.15, phase="transit", speed_limit_mps=0.55),
        RoutePoint(
            x=OFFICE_DOOR_CENTER_X,
            y=11.0,
            z=8.15,
            phase="transit",
            speed_limit_mps=0.55,
        ),
        RoutePoint(
            x=OFFICE_DOOR_CENTER_X,
            y=9.75,
            z=8.15,
            phase="transit",
            speed_limit_mps=0.55,
        ),
        RoutePoint(x=-35.0, y=8.02, z=8.12, phase="transit", speed_limit_mps=0.8),
        RoutePoint(x=-23.0, y=8.02, z=8.1, phase="transit", speed_limit_mps=0.8),
        RoutePoint(x=-12.0, y=8.02, z=8.08, phase="transit", speed_limit_mps=0.75),
        RoutePoint(x=-4.0, y=8.02, z=8.05, phase="transit", speed_limit_mps=0.65),
        *[
            RoutePoint(x=x, y=y, z=z, phase="stairs", speed_limit_mps=0.42)
            for x, y, z in school_map_stair_route_points("descending")
        ],
        RoutePoint(x=-3.0, y=8.02, z=1.05, phase="transit", speed_limit_mps=0.55),
        RoutePoint(x=-8.0, y=5.0, z=1.2, phase="transit", speed_limit_mps=0.65),
        RoutePoint(
            x=TEACHING_OPEN_DOOR_PAIR_CENTER_X,
            y=2.7,
            z=1.3,
            phase="transit",
            speed_limit_mps=0.5,
        ),
        RoutePoint(
            x=TEACHING_OPEN_DOOR_PAIR_CENTER_X,
            y=-1.055,
            z=1.4,
            phase="land",
            speed_limit_mps=0.35,
        ),
    ]


def _task_graph(
    steps: list[MissionStep],
    locale: Literal["en", "zh-CN"],
) -> MissionTaskGraph:
    """Expand intent into an auditable, fail-closed execution graph.

    The language model can describe goals, but every motion segment is gated by
    perception, corridor planning, dynamics checks and explicit completion
    evidence before the mission executive advances the graph.
    """

    nodes: list[MissionTaskNode] = []

    def text(english: str, chinese: str) -> str:
        return _localized(locale, english, chinese)

    def append_node(
        task_id: str,
        label: str,
        *,
        depends_on: list[str],
        executor: TaskExecutor,
        risk: TaskRisk,
        timeout_s: float,
        fallback: SafetyAction,
        expected_output: str,
        completion_evidence: list[str],
        max_retries: int = 2,
        status: TaskNodeStatus = "pending",
    ) -> str:
        nodes.append(
            MissionTaskNode(
                task_id=task_id,
                label=label,
                status=status,
                depends_on=depends_on,
                executor=executor,
                risk=risk,
                max_retries=max_retries,
                timeout_s=timeout_s,
                fallback=fallback,
                expected_output=expected_output,
                completion_evidence=completion_evidence,
            )
        )
        return task_id

    previous = append_node(
        "preflight-pack-identity",
        text(
            "Bind the immutable Vehicle Pack, firmware identity and control adapter",
            "绑定不可变的机型包、固件身份与控制适配器",
        ),
        depends_on=[],
        executor="mission_executive",
        risk="critical",
        max_retries=0,
        timeout_s=15.0,
        fallback="abort",
        expected_output=text(
            "Vehicle, firmware and adapter identities match the mission contract",
            "机型、固件与适配器身份均与任务合同一致",
        ),
        completion_evidence=["vehicle-pack.digest", "firmware.identity", "adapter.identity"],
        status="ready",
    )
    previous = append_node(
        "preflight-sensors",
        text(
            "Verify required sensor calibration, time synchronization and stream health",
            "验证所需传感器的校准、时间同步和数据流健康状态",
        ),
        depends_on=[previous],
        executor="perception",
        risk="critical",
        max_retries=1,
        timeout_s=30.0,
        fallback="abort",
        expected_output=text(
            "Every required localization and obstacle stream is healthy and synchronized",
            "全部定位与避障数据流均健康且已同步",
        ),
        completion_evidence=["sensor.calibration", "clock.offset", "stream.health"],
    )
    previous = append_node(
        "preflight-flight-envelope",
        text(
            "Validate mass, center of gravity, thrust, energy reserve and braking envelope",
            "验证质量、重心、推力、能量预留与制动包络",
        ),
        depends_on=[previous],
        executor="mission_executive",
        risk="critical",
        max_retries=0,
        timeout_s=20.0,
        fallback="abort",
        expected_output=text(
            "A task-specific flight-envelope qualification receipt",
            "生成针对本任务的飞行包络资格回执",
        ),
        completion_evidence=["mass.total", "cg.bound", "thrust.margin", "battery.reserve"],
    )
    previous = append_node(
        "world-map-binding",
        text(
            "Bind the selected Map Pack, coordinate frame, semantic entities and geofence",
            "绑定所选地图包、坐标系、语义实体与地理围栏",
        ),
        depends_on=[previous],
        executor="global_planner",
        risk="high",
        max_retries=1,
        timeout_s=30.0,
        fallback="hold",
        expected_output=text(
            "A versioned world frame with grounded mission entities and hard boundaries",
            "生成带版本的世界坐标系，并绑定任务实体和不可越界边界",
        ),
        completion_evidence=[
            "map-pack.digest",
            "frame.transform",
            "semantic.bindings",
            "geofence.version",
        ],
    )
    previous = append_node(
        "world-localization",
        text(
            "Establish bounded localization and initialize the live obstacle world model",
            "建立有界定位并初始化实时障碍物世界模型",
        ),
        depends_on=[previous],
        executor="perception",
        risk="critical",
        max_retries=2,
        timeout_s=45.0,
        fallback="hold",
        expected_output=text(
            "Localization covariance and observable free-space satisfy launch limits",
            "定位协方差与可观测自由空间满足起飞限制",
        ),
        completion_evidence=[
            "localization.covariance",
            "free-space.snapshot",
            "dynamic-overlay.age",
        ],
    )
    previous = append_node(
        "plan-global-corridor",
        text(
            "Generate the global route corridor and a payload-aware return alternative",
            "生成全局路线走廊与考虑载荷的备用返航路线",
        ),
        depends_on=[previous],
        executor="global_planner",
        risk="high",
        max_retries=3,
        timeout_s=60.0,
        fallback="hold",
        expected_output=text(
            "Primary and contingency corridors satisfy map, clearance and energy constraints",
            "主路线与备用路线均满足地图、净空和能量约束",
        ),
        completion_evidence=["corridor.primary", "corridor.contingency", "energy.projection"],
    )

    executor_by_action: dict[MissionAction, TaskExecutor] = {
        "takeoff": "px4_bridge",
        "transit": "local_planner",
        "traverse_stairs": "local_planner",
        "pass_gate": "local_planner",
        "pickup": "payload_controller",
        "return": "global_planner",
        "land": "px4_bridge",
    }
    risk_by_action: dict[MissionAction, TaskRisk] = {
        "takeoff": "high",
        "transit": "medium",
        "traverse_stairs": "high",
        "pass_gate": "high",
        "pickup": "high",
        "return": "medium",
        "land": "high",
    }
    for step in steps:
        prefix = f"mission-{step.order:02d}-{step.action.replace('_', '-')}"
        fallback: SafetyAction = "land" if step.action in {"return", "land"} else "hold"
        previous = append_node(
            f"{prefix}-observe",
            text(
                f"Refresh perception and confirm the local world before: {step.label}",
                f"执行“{step.label}”前刷新感知并确认局部环境",
            ),
            depends_on=[previous],
            executor="perception",
            risk=risk_by_action[step.action],
            max_retries=3,
            timeout_s=20.0,
            fallback="hold",
            expected_output=text(
                "A time-bounded local obstacle and semantic-target snapshot",
                "生成时间有效的局部障碍物与语义目标快照",
            ),
            completion_evidence=[
                "perception.sequence",
                "local-map.age",
                "tracked-entities.snapshot",
            ],
        )
        previous = append_node(
            f"{prefix}-plan",
            text(
                f"Plan or repair the local trajectory segment for: {step.label}",
                f"为“{step.label}”规划或修复局部航迹段",
            ),
            depends_on=[previous],
            executor="global_planner" if step.action == "return" else "local_planner",
            risk=risk_by_action[step.action],
            max_retries=3,
            timeout_s=45.0,
            fallback="hold",
            expected_output=text(
                "A collision-free, time-parameterized segment inside the approved corridor",
                "在已批准走廊内生成无碰撞、带时间参数的航迹段",
            ),
            completion_evidence=[
                "trajectory.revision",
                "corridor.containment",
                "clearance.prediction",
            ],
        )
        previous = append_node(
            f"{prefix}-qualify",
            text(
                f"Check geometry, dynamics, energy and safety policy for: {step.label}",
                f"检查“{step.label}”的几何、动力学、能量与安全策略",
            ),
            depends_on=[previous],
            executor="mission_executive",
            risk="critical" if step.action in {"takeoff", "land", "pickup"} else "high",
            max_retries=1,
            timeout_s=15.0,
            fallback=fallback,
            expected_output=text(
                "The proposed segment passes every deterministic execution gate",
                "候选航迹段通过全部确定性执行门禁",
            ),
            completion_evidence=["dynamics.acceptance", "energy.margin", "safety.acceptance"],
        )
        previous = append_node(
            f"{prefix}-execute",
            step.label,
            depends_on=[previous],
            executor=executor_by_action[step.action],
            risk=risk_by_action[step.action],
            max_retries=1 if step.action in {"takeoff", "land"} else 2,
            timeout_s=120.0 if step.action in {"transit", "traverse_stairs", "return"} else 45.0,
            fallback=fallback,
            expected_output=text(
                f"Controller-accepted completion of {step.action}",
                f"控制器确认完成动作：{step.label}",
            ),
            completion_evidence=["pose.trace", "clearance.minimum", "controller.acceptance"],
        )
        previous = append_node(
            f"{prefix}-verify",
            text(
                f"Verify completion evidence and settle the task state for: {step.label}",
                f"验证“{step.label}”的完成证据并确认任务状态",
            ),
            depends_on=[previous],
            executor="mission_executive",
            risk="high" if step.action in {"pickup", "land"} else "medium",
            max_retries=2,
            timeout_s=20.0,
            fallback=fallback,
            expected_output=text(
                "Completion evidence is consistent, current and attributable to this task",
                "完成证据一致、时效有效且可归因到本任务",
            ),
            completion_evidence=["task.result", "task.evidence", "world-state.revision"],
        )
        if step.action == "pickup":
            previous = append_node(
                f"{prefix}-recompute-envelope",
                text(
                    (
                        "Confirm payload attachment and recompute mass, center of gravity, "
                        "thrust and return energy"
                    ),
                    "确认载荷已经挂载，并重新计算质量、重心、推力与返航能量",
                ),
                depends_on=[previous],
                executor="mission_executive",
                risk="critical",
                max_retries=1,
                timeout_s=25.0,
                fallback="land",
                expected_output=text(
                    "The loaded aircraft remains inside its qualified return envelope",
                    "载荷后的无人机仍处于已验证的返航包络内",
                ),
                completion_evidence=[
                    "payload.confirmed",
                    "mass.loaded",
                    "cg.loaded",
                    "return-energy.margin",
                ],
            )
    previous = append_node(
        "postflight-state",
        text(
            "Confirm landing, disarm the vehicle and close command authority",
            "确认降落、解除无人机武装并关闭指令权限",
        ),
        depends_on=[previous],
        executor="px4_bridge",
        risk="critical",
        max_retries=1,
        timeout_s=20.0,
        fallback="abort",
        expected_output=text(
            "Landed and disarmed state with actuator authority revoked",
            "无人机已降落、已解除武装且执行器权限已撤销",
        ),
        completion_evidence=["vehicle.landed", "vehicle.disarmed", "authority.revoked"],
    )
    append_node(
        "postflight-evidence",
        text(
            "Seal mission results, anomalies, task revisions and replay evidence",
            "封存任务结果、异常、任务修订与回放证据",
        ),
        depends_on=[previous],
        executor="mission_executive",
        risk="low",
        max_retries=2,
        timeout_s=20.0,
        fallback="hold",
        expected_output=text(
            "A hash-chained mission evidence head",
            "生成任务哈希证据链头",
        ),
        completion_evidence=[
            "mission.result",
            "task-graph.revisions",
            "decision.log",
            "evidence.chain-head",
        ],
    )
    return MissionTaskGraph(
        nodes=nodes,
        active_node_ids=["preflight-pack-identity"],
        change_reason=text("compiled", "已完成编译"),
    )


def _route_metrics(points: list[RoutePoint]) -> tuple[float, float]:
    distance = 0.0
    vertical = 0.0
    for start, end in zip(points, points[1:], strict=False):
        dx, dy, dz = end.x - start.x, end.y - start.y, end.z - start.z
        distance += math.sqrt(dx * dx + dy * dy + dz * dz)
        vertical += abs(dz)
    return distance, vertical


def _policy(request: AutonomyCompileRequest, feasible: bool) -> ExecutionPolicy:
    target = request.execution_target
    adapter: ExecutionAdapter
    if target == "simulation":
        adapter = "px4_gazebo_contract"
    elif target == "hitl":
        adapter = "hitl_contract"
    else:
        adapter = "hardware_contract"
    blockers: list[str] = []
    required: list[str] = []
    planner_binding = (
        request.asset_context.planner_binding if request.asset_context is not None else None
    )

    if target != "simulation" and request.edition == "sim":
        blockers.append("edition.sim.forbids-hardware-and-hitl")
    if target != "simulation" and VALIDATED_SIGNED_PACK_COUNT == 0:
        blockers.append("vehicle-pack.registry.zero-validated-signed-packs")
    if target != "simulation" and not request.evidence.simulation_qualified:
        blockers.append("simulation-qualification.missing")
    if target != "simulation" and not request.evidence.signed_vehicle_pack_id:
        blockers.append("vehicle-pack.receipt.missing")
    if target != "simulation" and not request.evidence.operator_confirmed:
        blockers.append("operator.confirmation.missing")
    for ready, code in (
        (request.evidence.localization_ready, "localization.not-ready"),
        (request.evidence.link_ready, "command-link.not-ready"),
        (request.evidence.geofence_ready, "geofence.not-ready"),
        (request.evidence.battery_ready, "battery.not-ready"),
    ):
        if target != "simulation" and not ready:
            blockers.append(code)
    if not feasible:
        blockers.append("trajectory.not-feasible")
    if target == "simulation" and planner_binding is None:
        blockers.append("planner.model-artifact-binding.missing")

    if target == "simulation" and feasible and planner_binding is not None:
        return ExecutionPolicy(
            readiness="simulation_ready",
            adapter=adapter,
            can_execute=True,
            validated_signed_pack_count=VALIDATED_SIGNED_PACK_COUNT,
            blockers=[],
            required_next_steps=[
                _localized(
                    request.locale,
                    (
                        "Confirm the launch, run the fixed PX4/Gazebo mission, and retain its "
                        "evidence receipt."
                    ),
                    "确认起飞，运行已冻结的 PX4/Gazebo 任务，并保留其证据回执。",
                )
            ],
        )
    if blockers:
        if target == "simulation":
            required.extend(
                [
                    _localized(
                        request.locale,
                        (
                            "Adjust payload, speed, acceleration, or the vehicle envelope until "
                            "all trajectory feasibility checks pass."
                        ),
                        "调整载荷、速度、加速度或机型包络，直到全部航迹可行性检查通过。",
                    ),
                    _localized(
                        request.locale,
                        (
                            "Recompile the same simulation mission and review every reported "
                            "geometry or dynamics issue before qualification."
                        ),
                        "重新编译同一个仿真任务，并在资格认证前检查全部几何或动力学问题。",
                    ),
                ]
            )
        else:
            required.extend(
                [
                    _localized(
                        request.locale,
                        (
                            "Complete and sign the simulation qualification for the identical "
                            "mission contract."
                        ),
                        "为完全相同的任务合同完成并签署仿真资格认证。",
                    ),
                    _localized(
                        request.locale,
                        "Bind a validated signed Vehicle Pack and firmware identity.",
                        "绑定已验证且已签名的机型包与固件身份。",
                    ),
                    _localized(
                        request.locale,
                        "Obtain a short-lived operator confirmation after live preflight checks.",
                        "完成实时起飞前检查后，获取短时有效的操作员确认。",
                    ),
                ]
            )
        return ExecutionPolicy(
            readiness="denied",
            adapter=adapter,
            can_execute=False,
            validated_signed_pack_count=VALIDATED_SIGNED_PACK_COUNT,
            blockers=sorted(set(blockers)),
            required_next_steps=required,
        )
    return ExecutionPolicy(
        readiness="preview_only",
        adapter=adapter,
        can_execute=False,
        validated_signed_pack_count=VALIDATED_SIGNED_PACK_COUNT,
        blockers=["runtime.execution-adapter.not-bound"],
        required_next_steps=[
            _localized(
                request.locale,
                "Bind the audited runtime adapter before enabling execution.",
                "启用执行前，先绑定经过审计的运行时适配器。",
            )
        ],
    )


def compile_autonomy_mission(request: AutonomyCompileRequest) -> AutonomyCompileResponse:
    """Compile intent into a deterministic contract; never emit raw actuator commands."""

    scene_id = _select_scene(request)
    scene = get_scene(scene_id)
    if scene is None:  # defensive registry invariant
        raise AutonomyCompileError(
            "AUTONOMY_SCENE_UNAVAILABLE",
            "The terrain scene is unavailable.",
            503,
        )
    perception = _select_perception(request)
    mission_profile = school_mission_profile(request, scene_id)
    steps = _steps(
        scene_id,
        mission_profile,
        request.vehicle.pickup_payload_kg,
        request.locale,
    )
    task_graph = _task_graph(steps, request.locale)
    profile_path = (
        _school_reference_path(mission_profile) if scene_id == "school-campus-v1" else None
    )
    points = [
        point.model_copy(
            deep=True,
            update={
                "speed_limit_mps": min(
                    point.speed_limit_mps,
                    request.vehicle.max_speed_mps,
                )
            },
        )
        for point in profile_path or scene.reference_path
    ]
    route_length, vertical_travel = _route_metrics(points)
    launch_mass = request.vehicle.dry_mass_kg + request.vehicle.launch_payload_kg
    pickup_delta = (
        request.vehicle.pickup_payload_kg if any(step.action == "pickup" for step in steps) else 0.0
    )
    loaded_mass = launch_mass + pickup_delta
    thrust_to_weight = request.vehicle.max_total_thrust_n / (loaded_mass * GRAVITY)
    trajectory_speed_mps = max(
        (point.speed_limit_mps for point in points),
        default=request.vehicle.max_speed_mps,
    )
    braking_distance = (
        trajectory_speed_mps**2 / (2 * request.vehicle.max_acceleration_mps2)
        + request.vehicle.radius_m
    )
    issues: list[ValidationIssue] = []
    if loaded_mass - request.vehicle.max_takeoff_mass_kg > MASS_COMPARISON_TOLERANCE_KG:
        issues.append(
            ValidationIssue(
                code="vehicle.loaded-mass-exceeds-mtom",
                severity="error",
                message=_localized(
                    request.locale,
                    "Post-pickup mass exceeds the configured maximum takeoff mass.",
                    "取物后的总质量超过已配置的最大起飞质量。",
                ),
            )
        )
    if thrust_to_weight < MIN_THRUST_TO_WEIGHT:
        issues.append(
            ValidationIssue(
                code="vehicle.thrust-margin-insufficient",
                severity="error",
                message=_localized(
                    request.locale,
                    (
                        "Post-pickup thrust-to-weight must remain at least "
                        f"{MIN_THRUST_TO_WEIGHT:.2f}."
                    ),
                    f"取物后的推重比必须不低于 {MIN_THRUST_TO_WEIGHT:.2f}。",
                ),
            )
        )
    if braking_distance > scene.minimum_clearance_m:
        issues.append(
            ValidationIssue(
                code="trajectory.braking-envelope-exceeds-clearance",
                severity="error",
                message=_localized(
                    request.locale,
                    "The stopping envelope is larger than the scene's verified minimum clearance.",
                    "制动包络大于场景已验证的最小净空。",
                ),
            )
        )
    if perception == "map":
        issues.append(
            ValidationIssue(
                code="perception.static-map-no-live-obstacle-update",
                severity="warning",
                message=_localized(
                    request.locale,
                    (
                        "Map-only operation cannot qualify dynamic-obstacle response; use vision "
                        "or fusion for hardware handoff."
                    ),
                    "仅使用地图无法验证动态避障响应；移交真机前应使用视觉或融合感知。",
                ),
            )
        )
    if scene_id in {"school-campus-v1", "stairwell-coffee-return"} and perception == "vision":
        issues.append(
            ValidationIssue(
                code="perception.no-global-return-map",
                severity="warning",
                message=_localized(
                    request.locale,
                    (
                        "Vision-only return depends on retained route memory and relocalization "
                        "at each stair landing."
                    ),
                    "仅视觉返航依赖保留的路线记忆，并需要在每个楼梯平台重新定位。",
                ),
            )
        )
    issues.append(
        ValidationIssue(
            code="planner.reference-corridor-verified",
            severity="info",
            message=_localized(
                request.locale,
                (
                    "The route uses a bounded reference corridor with speed limits and "
                    "payload-aware return checks."
                ),
                "路线使用带速度限制的有界参考走廊，并包含考虑载荷的返航检查。",
            ),
        )
    )
    feasible = not any(issue.severity == "error" for issue in issues)

    canonical = {
        "edition": request.edition,
        "locale": request.locale,
        "execution_target": request.execution_target,
        "intent": request.natural_language,
        "scene_id": scene_id,
        "mission_profile": mission_profile,
        "perception_mode": perception,
        "steps": [step.model_dump(mode="json") for step in steps],
        "task_graph": task_graph.model_dump(mode="json"),
        "vehicle": request.vehicle.model_dump(mode="json"),
        "planner_binding": (
            request.asset_context.planner_binding.model_dump(mode="json")
            if request.asset_context is not None
            and request.asset_context.planner_binding is not None
            else None
        ),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    contract = MissionContract(
        contract_id=f"mission-{digest[:20]}",
        edition=request.edition,
        locale=request.locale,
        execution_target=request.execution_target,
        scene_id=scene_id,
        perception_mode=perception,
        intent=request.natural_language,
        steps=steps,
        task_graph=task_graph,
        immutable_safety_rules=[
            _localized(
                request.locale,
                (
                    "A language or vision model may propose mission goals but cannot issue "
                    "actuator commands."
                ),
                "语言或视觉模型可以提出任务目标，但不能直接发出执行器指令。",
            ),
            _localized(
                request.locale,
                "Every trajectory must pass geometry, dynamics, payload and edition-policy checks.",
                "每条航迹都必须通过几何、动力学、载荷与软件版本策略检查。",
            ),
            _localized(
                request.locale,
                (
                    "Loss of localization, command link or safety clearance transitions "
                    "execution to hold or abort."
                ),
                "定位、指令链路或安全净空丢失时，执行必须转入悬停或中止。",
            ),
            _localized(
                request.locale,
                (
                    "Hardware execution requires an independently signed simulation "
                    "qualification and operator challenge."
                ),
                "真机执行必须具备独立签名的仿真资格认证和操作员确认。",
            ),
        ],
    )
    metrics = MissionMetrics(
        route_length_m=route_length,
        vertical_travel_m=vertical_travel,
        estimated_duration_s=sum(
            math.dist((a.x, a.y, a.z), (b.x, b.y, b.z)) / min(a.speed_limit_mps, b.speed_limit_mps)
            for a, b in zip(points, points[1:], strict=False)
        ),
        minimum_clearance_m=scene.minimum_clearance_m,
        launch_mass_kg=launch_mass,
        post_pickup_mass_kg=loaded_mass,
        post_pickup_thrust_to_weight=thrust_to_weight,
        braking_distance_m=braking_distance,
    )
    return AutonomyCompileResponse(
        scene=scene,
        contract=contract,
        trajectory=points,
        feasible=feasible,
        issues=issues,
        metrics=metrics,
        execution_policy=_policy(request, feasible),
        planner={
            "binding": (
                "model-bound"
                if request.asset_context is not None
                and request.asset_context.planner_binding is not None
                else "missing"
            ),
            "artifact_sha256": (
                request.asset_context.planner_binding.artifact_sha256
                if request.asset_context is not None
                and request.asset_context.planner_binding is not None
                else ""
            ),
            "run_id": (
                request.asset_context.planner_binding.run_id
                if request.asset_context is not None
                and request.asset_context.planner_binding is not None
                else ""
            ),
            "semantic_layer": "bounded-natural-language-contract-v1",
            "global_layer": "prevalidated-corridor-graph-v1",
            "trajectory_layer": "payload-aware-speed-profile-v1",
            "safety_layer": "deterministic-geometric-policy-kernel-v1",
        },
        runtime_profile=runtime_profile_for(request),
    )


__all__ = [
    "AutonomyCompileError",
    "compile_autonomy_mission",
    "school_mission_profile",
]
