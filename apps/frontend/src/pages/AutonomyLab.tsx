import {
  AlertTriangle,
  ArrowUp,
  BadgeCheck,
  BrainCircuit,
  Camera,
  Check,
  CircleDotDashed,
  Coffee,
  Cpu,
  FileCheck2,
  LockKeyhole,
  Map,
  MessageSquareText,
  Navigation2,
  Pause,
  Play,
  Radar,
  RefreshCcw,
  Route,
  ShieldCheck,
  Sparkles,
  Weight,
  Waypoints,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { apiClient } from "../api/client";
import { BUILD_EDITION, EDITION_IS_FIXED } from "../edition";
import { createLocalAutonomyPreview } from "../features/autonomy/missionAutonomy";
import { autonomyHarnessRequest } from "../features/autonomy/missionHarness";
import {
  autonomyMapPackQualified,
  planAutonomyMission,
  type AutonomyPlanningModel,
} from "../features/autonomy/autonomyPlanning";
import { AutonomyWorld3D } from "../features/autonomy/AutonomyWorld3D";
import {
  autonomyAircraftRadiusM,
  isAutonomyAircraftAssetQualified,
  type AutonomyAircraftProfile,
  type AutonomyConversationMessage,
  type AutonomyEvidenceRecord,
  type AutonomyWorkspaceState,
} from "../features/autonomy/workspaceStore";
import { publicDemoConsole } from "../features/demo/publicDemo";
import {
  consumeAutonomyHandoff,
  loadAutonomyHandoff,
} from "../features/experiment/assistantTaskRouter";
import {
  loadUniversalMode,
  UNIVERSAL_WORKSPACE_CHANGED_EVENT,
} from "../features/distribution/universalMode";
import { localeSafeError, useI18n } from "../i18n/I18nProvider";
import type { InterfaceLocale } from "../i18n/I18nProvider";
import type {
  AutonomyCompileRequest,
  AutonomyCompileResponse,
  AutonomyEdition,
  AutonomyExecutionTarget,
  AutonomyPerceivedEntity,
  AutonomyRuntimeSession,
  AutonomySimulationExecution,
  AutonomyTaskGraph,
} from "../types/api";

type MissionId = "coffee" | "gates" | "narrow";
type PerceptionMode = "fusion" | "vision" | "map";
type Point = readonly [number, number];

const MISSION_STEP_PAYLOAD_LIMIT_KG = 10;

interface MissionPreset {
  id: MissionId;
  icon: typeof Coffee;
  name: string;
  description: string;
  objective: string;
  points: readonly Point[];
  replanPoints: readonly Point[];
  distance: string;
  eta: string;
  clearance: string;
}

interface AutonomyCopy {
  kicker: string;
  title: string;
  subtitle: string;
  simulationOnly: string;
  independent: string;
  commandTitle: string;
  commandHelp: string;
  compileCommand: string;
  compilingCommand: string;
  compileFailed: string;
  mapUnavailable: string;
  aircraftUnavailable: string;
  intentSource: string;
  editInChat: string;
  executionTarget: string;
  targets: Record<AutonomyExecutionTarget, string>;
  targetHelp: Record<AutonomyExecutionTarget, string>;
  contract: string;
  sourceBackend: string;
  sourcePreview: string;
  feasible: string;
  blocked: string;
  loadedMass: string;
  thrustMargin: string;
  payload: string;
  safetyGate: string;
  noBlockers: string;
  signedPacks: string;
  mission: string;
  perception: string;
  perceptionHelp: string;
  modes: Record<PerceptionMode, string>;
  modeDescriptions: Record<PerceptionMode, string>;
  missions: Record<MissionId, Pick<MissionPreset, "name" | "description" | "objective">>;
  taskFlow: string;
  start: string;
  via: string;
  destination: string;
  returnHome: string;
  plan: string;
  replan: string;
  planned: string;
  planning: string;
  environment: string;
  cameraFeed: string;
  mapped: string;
  unknown: string;
  run: string;
  pause: string;
  resume: string;
  reset: string;
  inject: string;
  running: string;
  completed: string;
  ready: string;
  replanning: string;
  brain: string;
  brainSubtitle: string;
  brainStages: readonly string[];
  telemetry: string;
  onboardRuntime: string;
  runtimeModes: Record<AutonomyCompileResponse["runtime_profile"]["mode"], string>;
  runtimeAwaiting: string;
  distance: string;
  clearance: string;
  eta: string;
  speed: string;
  checkpoint: string;
  confidence: string;
  eventLog: string;
  runtimeInstruction: string;
  runtimeInstructionPlaceholder: string;
  runtimeHolding: string;
  runtimePlanning: string;
  runtimeApplied: string;
  runtimeReplanFailed: string;
  sendRuntimeInstruction: string;
  events: {
    ready: string;
    planned: string;
    launched: string;
    paused: string;
    obstacle: string;
    completed: string;
  };
}

const EN_COPY: AutonomyCopy = {
  kicker: "MODEL + HARNESS AGENT",
  title: "Mission Agent",
  subtitle: "Describe a mission in ordinary language. DroneDream compiles a bounded task contract, validates terrain, payload and dynamics, then qualifies it for simulation before any hardware handoff.",
  simulationOnly: "SHARED AGENT CORE",
  independent: "Language intent · deterministic safety kernel",
  commandTitle: "Natural-language mission",
  commandHelp: "The model may structure intent, but it never emits actuator commands. Every result passes the same geometric and physical checks.",
  compileCommand: "Compile & qualify",
  compilingCommand: "Checking mission…",
  compileFailed: "The authoritative compiler did not approve this request. Check the runtime connection and mission inputs, then try again.",
  mapUnavailable: "Map Pack is not qualified. Calibrate it and bind a validated compiler scene before planning.",
  aircraftUnavailable: "Aircraft envelope is outside the compiler contract. Review mass, thrust, reserve, and planning radius.",
  intentSource: "Mission intent from Tuning Chat",
  editInChat: "Edit in Tuning Chat",
  executionTarget: "Execution target",
  targets: { simulation: "Simulation", hitl: "HITL", hardware: "Aircraft" },
  targetHelp: {
    simulation: "PX4 / Gazebo qualification contract",
    hitl: "Hardware-in-the-loop; signed vehicle identity required",
    hardware: "Real aircraft; operator and live preflight authority required",
  },
  contract: "Mission contract",
  sourceBackend: "BACKEND QUALIFIED",
  sourcePreview: "LOCAL CONTRACT PREVIEW",
  feasible: "Trajectory feasible",
  blocked: "Execution blocked",
  loadedMass: "Loaded mass",
  thrustMargin: "Thrust / weight",
  payload: "Pickup payload",
  safetyGate: "Safety & authority gate",
  noBlockers: "All simulation planning checks passed",
  signedPacks: "Validated signed packs",
  mission: "Mission",
  perception: "What the drone knows",
  perceptionHelp: "Choose the evidence available before takeoff. Vision modes continue updating the local world model in flight.",
  modes: { fusion: "Vision + map", vision: "Vision only", map: "Map only" },
  modeDescriptions: {
    fusion: "Global structure plus live depth and image observations",
    vision: "No prior map; reveal free space from the forward camera",
    map: "Plan from a known static occupancy map",
  },
  missions: {
    coffee: {
      name: "Coffee run",
      description: "Office → stairs → pickup → return",
      objective: "Collect the coffee, preserve route memory, and return to the launch point.",
    },
    gates: {
      name: "Gate sequence",
      description: "Center three circular gates",
      objective: "Cross each gate near its center while keeping a smooth, dynamically feasible trajectory.",
    },
    narrow: {
      name: "Narrow passage",
      description: "Start → via point → goal",
      objective: "Navigate a confined route and locally repair the path when clearance changes.",
    },
  },
  taskFlow: "Mission checkpoints",
  start: "Start",
  via: "Via",
  destination: "Pickup",
  returnHome: "Home",
  plan: "Plan trajectory",
  replan: "Replan trajectory",
  planned: "Trajectory ready",
  planning: "Building safe corridor…",
  environment: "World & trajectory",
  cameraFeed: "STATIC MAP + GPS · NO CAMERA/VIO",
  mapped: "mapped",
  unknown: "revealed live",
  run: "Fly mission",
  pause: "Pause",
  resume: "Resume",
  reset: "Reset",
  inject: "Add surprise obstacle",
  running: "Tracking trajectory",
  completed: "Mission complete",
  ready: "Ready to plan",
  replanning: "Local safety repair",
  brain: "Agent brain",
  brainSubtitle: "A slow semantic planner sets intent; a fast geometric loop keeps every command safe and flyable.",
  brainStages: ["Perceive", "Understand", "Plan", "Track", "Replan"],
  telemetry: "Live flight state",
  onboardRuntime: "Onboard runtime",
  runtimeModes: {
    simulation_contract: "SIMULATION BOUND",
    hitl_shadow: "HITL SHADOW",
    hardware_locked: "AIRCRAFT LOCKED",
  },
  runtimeAwaiting: "CONTRACT ONLY · NO LIVE SESSION",
  distance: "Route",
  clearance: "Min clearance",
  eta: "Mission ETA",
  speed: "Speed",
  checkpoint: "Next checkpoint",
  confidence: "Scene confidence",
  eventLog: "Decision trace",
  runtimeInstruction: "Update the active mission",
  runtimeInstructionPlaceholder: "Tell the aircraft what changed…",
  runtimeHolding: "Aircraft is holding at a safe setpoint while the update is interpreted.",
  runtimePlanning: "Validating a replacement task graph…",
  runtimeApplied: "Replacement task graph accepted. Flight resumed from the held position.",
  runtimeReplanFailed: "The aircraft remains safely held because the replacement plan was not accepted.",
  sendRuntimeInstruction: "Send mission update",
  events: {
    ready: "Mission loaded. Waiting for a trajectory.",
    planned: "Safe corridor and smooth trajectory generated.",
    launched: "Offboard mission started; local safety loop is active.",
    paused: "Trajectory tracking paused at the current setpoint.",
    obstacle: "New obstacle detected. Local segment repaired without changing the mission goal.",
    completed: "All checkpoints cleared and the mission contract is complete.",
  },
};

const ZH_COPY: AutonomyCopy = {
  kicker: "模型 + 脚手架智能体",
  title: "任务智能体",
  subtitle: "用自然语言描述任务，由 DroneDream 编译受约束任务合同，检查地形、载荷与动力学；真机移交前必须先通过同一合同的仿真资格验证。",
  simulationOnly: "五款软件共享智能体核心",
  independent: "语言理解 · 确定性安全内核",
  commandTitle: "自然语言任务",
  commandHelp: "模型只负责把意图结构化，不直接输出电机或姿态指令；几何与物理安全检查不可绕过。",
  compileCommand: "编译并验证",
  compilingCommand: "正在检查任务…",
  compileFailed: "权威后端未批准本次请求。请检查运行时连接和任务输入后重试。",
  mapUnavailable: "地图包尚未验证。请先完成校准并绑定已验证的编译场景。",
  aircraftUnavailable: "机型包络超出编译器合同。请检查质量、推力、电量预留和规划半径。",
  intentSource: "来自任务对话的任务意图",
  editInChat: "返回任务对话修改",
  executionTarget: "执行目标",
  targets: { simulation: "仿真", hitl: "半实物 HITL", hardware: "真机" },
  targetHelp: {
    simulation: "PX4 / Gazebo 仿真资格合同",
    hitl: "半实物闭环，需要签名机型身份",
    hardware: "真实飞行，需要操作员和实时预检授权",
  },
  contract: "任务合同",
  sourceBackend: "后端已验证",
  sourcePreview: "本地合同预演",
  feasible: "航迹可行",
  blocked: "执行已拒绝",
  loadedMass: "取物后总重",
  thrustMargin: "推重比",
  payload: "取物载荷",
  safetyGate: "安全与权限门",
  noBlockers: "仿真规划检查全部通过",
  signedPacks: "已验证签名机型包",
  mission: "任务",
  perception: "无人机已知信息",
  perceptionHelp: "选择起飞前可用的信息。使用视觉时，飞行中会持续更新局部环境模型。",
  modes: { fusion: "视觉 + 地图", vision: "仅视觉", map: "仅地图" },
  modeDescriptions: {
    fusion: "全局地图结构与实时图像、深度观测融合",
    vision: "没有先验地图，依靠前视相机逐步发现可飞空间",
    map: "根据已知静态占据地图完成全局规划",
  },
  missions: {
    coffee: {
      name: "取咖啡并返航",
      description: "办公室 → 楼梯 → 取货点 → 原路返回",
      objective: "取到咖啡，保留路径记忆并安全返回起飞点。",
    },
    gates: {
      name: "连续穿门",
      description: "依次穿过三个圆形门中心",
      objective: "尽量从每个圆门中心穿过，同时保持航迹平滑且满足动力学约束。",
    },
    narrow: {
      name: "狭窄通道",
      description: "起点 → 中间点 → 终点",
      objective: "穿越受限空间，并在净空变化时局部修复航迹。",
    },
  },
  taskFlow: "任务检查点",
  start: "起点",
  via: "中间点",
  destination: "取货点",
  returnHome: "返航点",
  plan: "规划航迹",
  replan: "重新规划",
  planned: "航迹已就绪",
  planning: "正在生成安全走廊…",
  environment: "环境与航迹",
  cameraFeed: "静态地图 + GPS · 未安装相机/VIO",
  mapped: "地图已知",
  unknown: "实时发现",
  run: "开始飞行",
  pause: "暂停",
  resume: "继续",
  reset: "复位",
  inject: "加入突发障碍",
  running: "正在跟踪航迹",
  completed: "任务完成",
  ready: "等待规划",
  replanning: "局部安全修正",
  brain: "任务智能体大脑",
  brainSubtitle: "低频语义规划负责理解任务，高频几何安全环保证每条指令都安全、可飞。",
  brainStages: ["感知", "理解", "规划", "跟踪", "重规划"],
  telemetry: "实时飞行状态",
  onboardRuntime: "机载运行底座",
  runtimeModes: {
    simulation_contract: "仿真合同已绑定",
    hitl_shadow: "HITL 影子模式",
    hardware_locked: "真机保持锁定",
  },
  runtimeAwaiting: "仅运行合同 · 尚未创建实时会话",
  distance: "航程",
  clearance: "最小净空",
  eta: "预计耗时",
  speed: "速度",
  checkpoint: "下一检查点",
  confidence: "场景置信度",
  eventLog: "决策记录",
  runtimeInstruction: "调整正在执行的任务",
  runtimeInstructionPlaceholder: "告诉无人机现场发生了什么变化…",
  runtimeHolding: "无人机已停在安全设定点，正在理解新的要求。",
  runtimePlanning: "正在验证新的任务图…",
  runtimeApplied: "新的任务图已通过验证，无人机从悬停位置继续执行。",
  runtimeReplanFailed: "新计划未通过验证，无人机将继续安全悬停。",
  sendRuntimeInstruction: "发送任务调整",
  events: {
    ready: "任务已载入，等待生成航迹。",
    planned: "安全走廊与平滑航迹已生成。",
    launched: "仿真任务已起飞，局部安全环正在工作。",
    paused: "航迹跟踪已停在当前设定点。",
    obstacle: "检测到新障碍，已局部修复航迹且未改变任务目标。",
    completed: "全部检查点已通过，任务流程完成。",
  },
};

const COPY_BY_LOCALE: Readonly<Record<InterfaceLocale, AutonomyCopy>> = {
  en: EN_COPY,
  "zh-CN": ZH_COPY,
};

const BASE_MISSIONS: Readonly<Record<MissionId, Omit<MissionPreset, "name" | "description" | "objective">>> = {
  coffee: {
    id: "coffee",
    icon: Coffee,
    points: [[88, 438], [208, 438], [276, 382], [340, 302], [450, 265], [565, 263], [654, 198], [814, 155], [654, 198], [568, 326], [430, 354], [290, 414], [88, 438]],
    replanPoints: [[88, 438], [208, 438], [276, 382], [340, 302], [450, 265], [565, 263], [654, 198], [814, 155], [654, 198], [595, 350], [492, 390], [365, 372], [290, 414], [88, 438]],
    distance: "48.6 m",
    eta: "01:24",
    clearance: "0.74 m",
  },
  gates: {
    id: "gates",
    icon: CircleDotDashed,
    points: [[88, 330], [230, 308], [360, 250], [500, 292], [650, 220], [814, 276]],
    replanPoints: [[88, 330], [230, 308], [360, 250], [472, 355], [570, 356], [650, 220], [814, 276]],
    distance: "32.4 m",
    eta: "00:38",
    clearance: "0.61 m",
  },
  narrow: {
    id: "narrow",
    icon: Waypoints,
    points: [[88, 410], [205, 388], [286, 330], [390, 322], [478, 242], [594, 235], [690, 170], [826, 146]],
    replanPoints: [[88, 410], [205, 388], [286, 330], [390, 322], [448, 395], [548, 404], [615, 325], [690, 170], [826, 146]],
    distance: "27.9 m",
    eta: "00:46",
    clearance: "0.48 m",
  },
};

const SCENE_ID_BY_MISSION: Record<MissionId, string> = {
  coffee: "school-campus-v1",
  gates: "school-campus-v1",
  narrow: "school-campus-v1",
};

const MISSION_BY_LEGACY_SCENE_ID: Record<string, MissionId> = {
  "stairwell-coffee-return": "coffee",
  "forest-gate-inspection": "gates",
  "service-corridor-dock": "narrow",
};

const DEFAULT_VEHICLE: AutonomyCompileRequest["vehicle"] = {
  dry_mass_kg: 2.0643076923076924,
  launch_payload_kg: 0,
  pickup_payload_kg: 0.1,
  max_takeoff_mass_kg: 2.164307692307692,
  max_total_thrust_n: 34.19432,
  radius_m: 0.38,
  max_speed_mps: 4.0,
  max_acceleration_mps2: 2.5,
  reserve_battery_percent: 30,
};

function missionForWorkspace(workspace?: AutonomyWorkspaceState): MissionId {
  if (!workspace) return "coffee";
  const boundMission = workspace.mapPack.compilerSceneId
    ? MISSION_BY_LEGACY_SCENE_ID[workspace.mapPack.compilerSceneId]
    : undefined;
  if (boundMission) return boundMission;
  const intent = workspace.mission.intent.toLowerCase();
  if (/\bgates?\b|圆环|圆门|穿门/u.test(intent)) return "gates";
  if (/narrow|corridor|passage|狭窄|走廊/u.test(intent)) return "narrow";
  return "coffee";
}

function perceptionForWorkspace(workspace?: AutonomyWorkspaceState): PerceptionMode {
  if (!workspace) return "fusion";
  const hasMap = workspace.mapPack.calibrated && Boolean(workspace.mapPack.compilerSceneId);
  const hasVision = workspace.aircraft.sensors.some((sensor) => ["rgb", "depth", "stereo", "thermal", "vio"].includes(sensor));
  if (hasMap && hasVision) return "fusion";
  return hasVision ? "vision" : "map";
}

function vehicleForAircraft(aircraft?: AutonomyAircraftProfile): AutonomyCompileRequest["vehicle"] {
  if (!aircraft) return DEFAULT_VEHICLE;
  const payloadMarginKg = Math.max(0, aircraft.maximumTakeoffMassKg - aircraft.dryMassKg);
  const launchPayloadKg = Math.min(DEFAULT_VEHICLE.launch_payload_kg, payloadMarginKg);
  const pickupCapacityKg = Math.max(0, Math.min(
    aircraft.maximumPickupPayloadKg,
    payloadMarginKg - launchPayloadKg,
    MISSION_STEP_PAYLOAD_LIMIT_KG,
  ));
  return {
    ...DEFAULT_VEHICLE,
    dry_mass_kg: aircraft.dryMassKg,
    launch_payload_kg: launchPayloadKg,
    pickup_payload_kg: pickupCapacityKg,
    max_takeoff_mass_kg: aircraft.maximumTakeoffMassKg,
    max_total_thrust_n: aircraft.maximumThrustN,
    radius_m: autonomyAircraftRadiusM(aircraft),
    max_speed_mps: aircraft.maximumSpeedMps,
    max_acceleration_mps2: aircraft.maximumAccelerationMps2,
    reserve_battery_percent: aircraft.reserveBatteryPercent,
  };
}

function defaultTarget(edition: AutonomyEdition): AutonomyExecutionTarget {
  if (edition === "field") return "hardware";
  if (edition === "lab") return "hitl";
  return "simulation";
}

function loadAutonomyEdition(): AutonomyEdition {
  return EDITION_IS_FIXED ? BUILD_EDITION : loadUniversalMode();
}

function promptForMission(missionId: MissionId, chinese: boolean) {
  if (chinese) {
    if (missionId === "gates") return "在 School Map 校园道路起飞，依次穿过三座训练圆门的中心，避开树木、路灯和动态行人后平稳降落。";
    if (missionId === "narrow") return "从 School Map 三楼办公室起飞，穿过教室走廊与两段 12+12 折返楼梯，在一楼大厅目标点精准降落。";
    return "从三楼办公室起飞，穿过狭窄楼梯到一楼室外，避开树、建筑物、告示牌和立柱，在外卖取件点取到 0.10 kg 载荷后重新检查动力学并安全返回原起点。";
  }
  if (missionId === "gates") return "Launch on the School Map campus road, cross the centers of all three training gates, avoid trees, lights and moving people, then land smoothly.";
  if (missionId === "narrow") return "Launch from the School Map third-floor office, traverse the classroom corridor and both 12+12 switchback stairs, then land precisely in the lobby.";
  return "Launch from the third-floor office, descend the narrow stairs, avoid trees, buildings, signs and poles, collect the 0.10 kg payload at the takeout pickup, recheck dynamics, and return safely to the launch point.";
}

function interpolatePath(points: readonly Point[], progress: number): Point {
  if (points.length === 0) return [0, 0];
  if (points.length === 1) return points[0];
  const segmentProgress = Math.min(0.999999, Math.max(0, progress)) * (points.length - 1);
  const segment = Math.floor(segmentProgress);
  const local = segmentProgress - segment;
  const from = points[segment];
  const to = points[Math.min(segment + 1, points.length - 1)];
  return [from[0] + (to[0] - from[0]) * local, from[1] + (to[1] - from[1]) * local];
}

function eventTime() {
  return new Intl.DateTimeFormat(undefined, { minute: "2-digit", second: "2-digit" }).format(new Date());
}

function runtimeComponentLabel(
  id: AutonomyCompileResponse["runtime_profile"]["components"][number]["id"],
  chinese: boolean,
  mapOnly: boolean,
): string {
  const labels = chinese ? {
    mission_executive: "任务状态机",
    perception_vio_slam: mapOnly ? "地图 / GPS 定位" : "感知 / VIO / SLAM",
    world_model: "实时世界模型",
    global_planner: "全局规划器",
    local_planner: "局部重规划",
    trajectory_tracker: "航迹跟踪器",
    px4_bridge: "PX4 控制桥",
    safety_supervisor: "独立安全监督",
    evidence_recorder: "证据记录器",
  } : {
    mission_executive: "Mission executive",
    perception_vio_slam: mapOnly ? "Map / GPS localization" : "Perception / VIO / SLAM",
    world_model: "Live world model",
    global_planner: "Global planner",
    local_planner: "Local replanner",
    trajectory_tracker: "Trajectory tracker",
    px4_bridge: "PX4 bridge",
    safety_supervisor: "Safety supervisor",
    evidence_recorder: "Evidence recorder",
  };
  return labels[id];
}

function simulatedStreamHealth() {
  return [
    { stream_id: "school-map-prior", kind: "map" as const, source: "simulator" as const, status: "healthy" as const, rate_hz: 10, latency_ms: 0, dropped_percent: 0 },
  ];
}

function simulatedPerson(position: Point): AutonomyPerceivedEntity {
  return {
    track_id: "person-017",
    kind: "person",
    position_m: { x: position[0] / 20 + 0.75, y: position[1] / 20, z: 1.1 },
    velocity_mps: { x: 0, y: 0.65, z: 0 },
    confidence: 0.94,
    safety_radius_m: 1.2,
    age_ms: 38,
    source_stream: "front-rgb",
  };
}

function previewRuntimeTaskGraph(
  source: AutonomyTaskGraph,
  progress: number,
  dynamicEntityActive: boolean,
  obstacleInjected: boolean,
  chinese: boolean,
): AutonomyTaskGraph {
  const nodes = source.nodes.map((node) => ({ ...node, depends_on: [...node.depends_on], completion_evidence: [...node.completion_evidence] }));
  const completedCount = Math.min(nodes.length - 1, Math.floor(progress * nodes.length));
  nodes.forEach((node, index) => {
    node.status = index < completedCount ? "completed" : index === completedCount ? "active" : "pending";
  });
  if (obstacleInjected) {
    const anchor = [...nodes].reverse().find((node) => node.status === "completed")?.task_id ?? nodes[0].task_id;
    nodes.push({
      task_id: "runtime-hold-person-017",
      label: chinese
        ? "保护已跟踪行人 person-017 周围的安全包络"
        : "Protect the safety envelope around tracked person person-017",
      status: dynamicEntityActive ? "active" : "completed",
      depends_on: [anchor],
      executor: "mission_executive",
      risk: "critical",
      max_retries: 0,
      timeout_s: 120,
      fallback: "land",
      expected_output: chinese
        ? "恢复安全净空，或选定有边界的备用走廊"
        : "Clearance restored or a bounded alternative corridor selected",
      completion_evidence: ["entity.track", "entity.range", "safety.decision"],
      inserted_by: "runtime",
    });
    nodes.push({
      task_id: "runtime-replan-person-017",
      label: chinese
        ? "绕过 person-017 修复局部走廊并重新接入任务图"
        : "Repair the local corridor around person-017 and rejoin the mission graph",
      status: dynamicEntityActive ? "blocked" : "completed",
      depends_on: ["runtime-hold-person-017"],
      executor: "local_planner",
      risk: "high",
      max_retries: 3,
      timeout_s: 20,
      fallback: "hold",
      expected_output: chinese
        ? "在已批准走廊内生成通过碰撞检查的航迹修订"
        : "A collision-checked trajectory revision inside the approved corridor",
      completion_evidence: ["trajectory.revision", "clearance.minimum", "planner.receipt"],
      inserted_by: "runtime",
    });
  }
  return {
    ...source,
    revision: source.revision + (obstacleInjected ? 2 : progress > 0 ? 1 : 0),
    nodes,
    active_node_ids: nodes.filter((node) => node.status === "active").map((node) => node.task_id),
    change_reason: dynamicEntityActive
      ? (chinese ? "动态行人触发安全悬停与恢复分支" : "dynamic person inserted a safety hold and recovery branch")
      : obstacleInjected
        ? (chinese ? "局部走廊已修复，任务图恢复执行" : "local corridor repaired; mission graph resumed")
        : progress > 0
          ? (chinese ? "任务进度已推进编译任务" : "mission progress advanced compiler tasks")
          : source.change_reason,
  };
}

type TaskNode = AutonomyTaskGraph["nodes"][number];

const TASK_STATUS_LABELS: Record<TaskNode["status"], readonly [string, string]> = {
  pending: ["Pending", "等待中"],
  ready: ["Ready", "已就绪"],
  active: ["Active", "执行中"],
  blocked: ["Blocked", "已阻止"],
  completed: ["Completed", "已完成"],
  failed: ["Failed", "失败"],
  skipped: ["Skipped", "已跳过"],
};

const EXECUTOR_LABELS: Record<TaskNode["executor"], readonly [string, string]> = {
  language_model: ["Language model", "语言模型"],
  mission_executive: ["Mission executive", "任务执行器"],
  perception: ["Perception", "感知系统"],
  global_planner: ["Global planner", "全局规划器"],
  local_planner: ["Local planner", "局部规划器"],
  payload_controller: ["Payload controller", "载荷控制器"],
  px4_bridge: ["PX4 bridge", "PX4 桥接器"],
  operator: ["Operator", "操作员"],
};

const RISK_LABELS: Record<TaskNode["risk"], readonly [string, string]> = {
  low: ["Low", "低风险"],
  medium: ["Medium", "中风险"],
  high: ["High", "高风险"],
  critical: ["Critical", "关键风险"],
};

const FALLBACK_LABELS: Record<TaskNode["fallback"], readonly [string, string]> = {
  continue: ["Continue", "继续"],
  hold: ["Hold", "悬停"],
  land: ["Land", "降落"],
  abort: ["Abort", "中止"],
};

const STREAM_KIND_LABELS: Record<string, readonly [string, string]> = {
  rgb: ["RGB", "彩色图像"],
  depth: ["Depth", "深度图像"],
  stereo: ["Stereo", "双目视觉"],
  thermal: ["Thermal", "热成像"],
  lidar: ["LiDAR", "激光雷达"],
  vio: ["VIO", "视觉惯性里程计"],
  slam: ["SLAM", "同步定位与建图"],
  map: ["Map", "地图"],
};

const ENTITY_KIND_LABELS: Record<string, readonly [string, string]> = {
  person: ["Person", "行人"],
  vehicle: ["Vehicle", "车辆"],
  animal: ["Animal", "动物"],
  obstacle: ["Obstacle", "障碍物"],
  unknown: ["Unknown", "未知实体"],
};

const ADAPTER_LABELS: Record<string, readonly [string, string]> = {
  px4_gazebo_contract: ["PX4/Gazebo contract", "PX4/Gazebo 执行合同"],
  hitl_contract: ["HITL contract", "半实物仿真合同"],
  hardware_contract: ["Hardware contract", "真机执行合同"],
};

const RUNTIME_PHASE_LABELS: Record<string, readonly [string, string]> = {
  ready: ["Ready", "已就绪"],
  starting: ["Starting", "正在启动"],
  running: ["Running", "正在运行"],
  takeoff: ["Takeoff", "正在起飞"],
  navigating: ["Navigating", "正在导航"],
  pickup: ["Pickup", "正在取物"],
  replanning: ["Replanning", "正在重规划"],
  returning: ["Returning", "正在返航"],
  landing: ["Landing", "正在降落"],
  holding: ["Holding", "正在悬停"],
  completed: ["Completed", "已完成"],
  verified: ["Verified", "已验证"],
  failed: ["Failed", "失败"],
  aborting: ["Aborting", "正在中止"],
  aborted: ["Aborted", "已中止"],
};

const BLOCKER_LABELS: Record<string, readonly [string, string]> = {
  "vehicle-pack.registry.zero-validated-signed-packs": ["No validated signed Vehicle Pack is bound", "尚未绑定已验证且已签名的机型包"],
  "simulation-qualification.missing": ["Simulation qualification is missing", "缺少仿真资格认证"],
  "vehicle-pack.receipt.missing": ["Vehicle Pack receipt is missing", "缺少机型包回执"],
  "operator.confirmation.missing": ["Operator confirmation is missing", "缺少操作员确认"],
  "localization.not-ready": ["Localization is not ready", "定位尚未就绪"],
  "command-link.not-ready": ["Command link is not ready", "指令链路尚未就绪"],
  "geofence.not-ready": ["Geofence is not ready", "地理围栏尚未就绪"],
  "battery.not-ready": ["Battery state is not ready", "电池状态尚未就绪"],
  "edition.sim.forbids-hardware-and-hitl": ["SIM does not permit hardware or HITL execution", "SIM 不允许真机或半实物执行"],
  "trajectory.not-feasible": ["Trajectory is not feasible", "航迹不可执行"],
  "runtime.execution-adapter.not-bound": ["Runtime execution adapter is not bound", "尚未绑定运行时执行适配器"],
};

function localizedLabel(labels: readonly [string, string] | undefined, fallback: string, chinese: boolean) {
  if (!labels) return fallback;
  return chinese ? labels[1] : labels[0];
}

function embeddedTaskGraphNodes(graph: AutonomyTaskGraph): AutonomyTaskGraph["nodes"] {
  if (graph.nodes.length <= 2) return graph.nodes;

  const activeIds = new Set(graph.active_node_ids);
  const relevantIndexes = graph.nodes
    .map((node, index) => ({ node, index }))
    .filter(({ node }) =>
      activeIds.has(node.task_id)
      || node.status === "active"
      || node.status === "blocked"
      || node.status === "failed",
    );
  const runtimeIndexes = relevantIndexes
    .filter(({ node }) => node.inserted_by === "runtime")
    .map(({ index }) => index);
  const selected = new Set<number>(runtimeIndexes.slice(-2));

  for (const { index } of [...relevantIndexes].reverse()) {
    if (selected.size >= 2) break;
    selected.add(index);
  }

  if (selected.size === 0) {
    selected.add(graph.nodes.length - 1);
  }
  if (selected.size === 1) {
    const [anchor] = selected;
    selected.add(anchor > 0 ? anchor - 1 : Math.min(1, graph.nodes.length - 1));
  }

  return [...selected]
    .sort((left, right) => left - right)
    .map((index) => graph.nodes[index]);
}

export function AutonomyLab({
  embedded = false,
  onRunCompleted,
  onWorkspaceChange,
  planningModel = null,
  accountId = null,
  workspace,
}: {
  embedded?: boolean;
  onRunCompleted?: (record: AutonomyEvidenceRecord) => void;
  onWorkspaceChange?: (workspace: AutonomyWorkspaceState) => void;
  planningModel?: AutonomyPlanningModel | null;
  accountId?: string | null;
  workspace?: AutonomyWorkspaceState;
} = {}) {
  const { interfaceLocale } = useI18n();
  const copy = COPY_BY_LOCALE[interfaceLocale] ?? EN_COPY;
  const chinese = interfaceLocale === "zh-CN";
  const workspaceMissionId = missionForWorkspace(workspace);
  const workspaceVehicleKey = workspace
    ? [
        workspace.aircraft.dryMassKg,
        workspace.aircraft.maximumTakeoffMassKg,
        workspace.aircraft.maximumThrustN,
        workspace.aircraft.bodyLengthM,
        workspace.aircraft.bodyWidthM,
        workspace.aircraft.rotorRadiusM,
        workspace.aircraft.reserveBatteryPercent,
        workspace.aircraft.maximumPickupPayloadKg,
        workspace.aircraft.maximumSpeedMps,
        workspace.aircraft.maximumAccelerationMps2,
      ].join(":")
    : "default";
  const workspaceVehicleCache = useRef<{ key: string; value: AutonomyCompileRequest["vehicle"] } | null>(null);
  if (workspaceVehicleCache.current?.key !== workspaceVehicleKey) {
    workspaceVehicleCache.current = { key: workspaceVehicleKey, value: vehicleForAircraft(workspace?.aircraft) };
  }
  const workspaceVehicle = workspaceVehicleCache.current.value;
  const [edition, setEdition] = useState<AutonomyEdition>(loadAutonomyEdition);
  const [missionId, setMissionId] = useState<MissionId>(workspaceMissionId);
  const [perception, setPerception] = useState<PerceptionMode>(() => perceptionForWorkspace(workspace));
  const [target, setTarget] = useState<AutonomyExecutionTarget>(() => defaultTarget(loadAutonomyEdition()));
  const [command, setCommand] = useState(
    () => workspace?.mission.intent ?? loadAutonomyHandoff() ?? promptForMission(workspaceMissionId, chinese),
  );
  const [pickupPayloadKg, setPickupPayloadKg] = useState(workspaceVehicle.pickup_payload_kg);
  const [compileResult, setCompileResult] = useState<AutonomyCompileResponse | null>(null);
  const [compileSource, setCompileSource] = useState<"backend" | "preview">("preview");
  const [compileError, setCompileError] = useState<string | null>(null);
  const compileGeneration = useRef(0);
  const launchGeneration = useRef(0);
  const authorizedCompileRequest = useRef<AutonomyCompileRequest | null>(null);
  const [planned, setPlanned] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [running, setRunning] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [paused, setPaused] = useState(false);
  const [complete, setComplete] = useState(false);
  const [progress, setProgress] = useState(0);
  const [obstacleInjected, setObstacleInjected] = useState(false);
  const [dynamicEntityActive, setDynamicEntityActive] = useState(false);
  const [runtimeSession, setRuntimeSession] = useState<AutonomyRuntimeSession | null>(null);
  const [simulationExecution, setSimulationExecution] = useState<AutonomySimulationExecution | null>(null);
  const [runtimeInstruction, setRuntimeInstruction] = useState("");
  const [runtimeReplanning, setRuntimeReplanning] = useState(false);
  const [runtimeReplanError, setRuntimeReplanError] = useState<string | null>(null);
  const runtimeSessionRef = useRef<AutonomyRuntimeSession | null>(null);
  const simulationExecutionRef = useRef<AutonomySimulationExecution | null>(null);
  runtimeSessionRef.current = runtimeSession;
  simulationExecutionRef.current = simulationExecution;
  const runtimeRequestId = useRef<string | null>(null);
  const simulationExecutionRequestId = useRef<string | null>(null);
  const simulationTerminalHandled = useRef(false);
  const evidenceReported = useRef(false);
  const dynamicEntityTimer = useRef<number | null>(null);
  const previewRunId = useRef<string | null>(null);
  const workspaceBindingApplied = useRef<string | null>(null);
  const runtimeWorkspaceUpdateIntent = useRef<string | null>(null);
  const dronePositionRef = useRef<Point>([0, 0]);
  const [events, setEvents] = useState(() => [{ time: eventTime(), text: copy.events.ready }]);
  const [taskGraphView, setTaskGraphView] = useState<"summary" | "engineering">("summary");
  const workspaceBindingKey = workspace
    ? `${workspace.aircraft.updatedAt}:${workspace.mapPack.updatedAt}:${workspace.mission.updatedAt}:${workspace.mission.intent}`
    : "standalone";
  const stopActiveSimulation = useCallback((reason: string) => {
    if (publicDemoConsole) return;
    const activeExecution = simulationExecutionRef.current;
    const activeRuntime = runtimeSessionRef.current;
    const cleanupRequests: Array<Promise<unknown>> = [];
    if (
      activeExecution
      && !["verified", "failed", "aborted"].includes(activeExecution.state)
    ) {
      cleanupRequests.push(apiClient.abortAutonomySimulationExecution(
        activeExecution.execution_id,
        reason,
      ));
    }
    if (
      activeRuntime
      && !activeRuntime.terminal
      && activeExecution?.state !== "verified"
    ) {
      cleanupRequests.push(apiClient.stopAutonomyRuntimeSession(
        activeRuntime.session_id,
        "abort",
        reason,
      ));
    }
    if (cleanupRequests.length > 0) void Promise.allSettled(cleanupRequests);
  }, []);

  useEffect(() => {
    if (workspaceBindingApplied.current === workspaceBindingKey) return;
    workspaceBindingApplied.current = workspaceBindingKey;
    if (!workspace) {
      consumeAutonomyHandoff();
      return;
    }
    if (
      !runtimeSessionRef.current
      || runtimeSessionRef.current.terminal
      || workspace.mission.intent !== runtimeWorkspaceUpdateIntent.current
    ) {
      setCommand(workspace.mission.intent);
    }
    setMissionId(missionForWorkspace(workspace));
    setPerception(perceptionForWorkspace(workspace));
    setPickupPayloadKg(vehicleForAircraft(workspace.aircraft).pickup_payload_kg);
  }, [workspace, workspaceBindingKey]);

  useEffect(() => {
    if (EDITION_IS_FIXED) return undefined;
    const handleMode = () => setEdition(loadAutonomyEdition());
    window.addEventListener(UNIVERSAL_WORKSPACE_CHANGED_EVENT, handleMode);
    return () => window.removeEventListener(UNIVERSAL_WORKSPACE_CHANGED_EVENT, handleMode);
  }, []);

  useEffect(() => () => {
    launchGeneration.current += 1;
    stopActiveSimulation("Autonomy workspace closed while the simulation was active.");
  }, [stopActiveSimulation]);

  useEffect(() => {
    setTarget(defaultTarget(edition));
    setCompileResult(null);
    setPlanned(false);
    authorizedCompileRequest.current = null;
  }, [edition]);

  const missions = useMemo(() => Object.values(BASE_MISSIONS).map((base) => ({
    ...base,
    ...copy.missions[base.id],
  })), [copy]);
  const mission = missions.find(({ id }) => id === missionId) ?? missions[0];
  const hasWorkspace = workspace !== undefined;
  const workspaceCompilerSceneId = workspace?.mapPack.compilerSceneId;
  const workspaceMapQualified = workspace
    ? autonomyMapPackQualified(workspace.mapPack)
    : false;
  const workspaceAircraftQualified = workspace
    ? isAutonomyAircraftAssetQualified(workspace.aircraft)
    : false;
  const compileRequest = useMemo<AutonomyCompileRequest>(() => ({
    edition,
    locale: chinese ? "zh-CN" : "en",
    execution_target: target,
    natural_language: command.trim() || promptForMission(missionId, chinese),
    scene_id: workspaceCompilerSceneId ?? (hasWorkspace ? "" : SCENE_ID_BY_MISSION[missionId]),
    perception_mode: perception,
    vehicle: { ...workspaceVehicle, pickup_payload_kg: pickupPayloadKg },
    evidence: {
      simulation_qualified: false,
      signed_vehicle_pack_id: null,
      operator_confirmed: false,
      localization_ready: false,
      link_ready: false,
      geofence_ready: false,
      battery_ready: false,
    },
    asset_context: null,
  }), [chinese, command, edition, hasWorkspace, missionId, perception, pickupPayloadKg, target, workspaceCompilerSceneId, workspaceVehicle]);
  const latestCompileRequest = useRef(compileRequest);
  latestCompileRequest.current = compileRequest;
  const provisionalResult = useMemo(
    () => createLocalAutonomyPreview(missionId, compileRequest),
    [compileRequest, missionId],
  );
  const qualification = compileResult ?? provisionalResult;
  const localTaskGraph = useMemo(
    () => previewRuntimeTaskGraph(
      qualification.contract.task_graph,
      progress,
      dynamicEntityActive,
      obstacleInjected,
      chinese,
    ),
    [chinese, dynamicEntityActive, obstacleInjected, progress, qualification.contract.task_graph],
  );
  const activeTaskGraph = runtimeSession?.task_graph ?? localTaskGraph;
  const activeEntities = runtimeSession?.perceived_entities
    ?? (dynamicEntityActive ? [simulatedPerson(dronePositionRef.current)] : []);
  const editionLabel = ({
    universal: "UNIVERSAL",
    sim: "SIM",
    lab: "LAB",
    field: "FIELD",
    autonomy: "AGENT",
  } as const)[edition];
  const activePoints = obstacleInjected ? mission.replanPoints : mission.points;
  const [droneX, droneY] = interpolatePath(activePoints, progress);
  dronePositionRef.current = [droneX, droneY];
  const nextCheckpoint = missionId === "coffee"
    ? progress < 0.42 ? copy.destination : progress < 0.94 ? copy.returnHome : copy.start
    : progress < 0.55 ? copy.via : copy.destination;
  const liveSpeed = simulationExecution?.vehicle_speed_m_s !== null
    && simulationExecution?.vehicle_speed_m_s !== undefined
    ? `${simulationExecution.vehicle_speed_m_s.toFixed(2)} m/s`
    : publicDemoConsole && running && !paused
      ? `${(2.1 + Math.sin(progress * 18) * 0.35).toFixed(1)} m/s`
      : "0.0 m/s";
  const confidence = perception === "map" ? "100%" : `${Math.round(86 + progress * 10)}%`;
  const simulationExecutionId = simulationExecution?.execution_id;
  const simulationExecutionState = simulationExecution?.state;
  const runtimeSessionTerminal = runtimeSession?.terminal ?? false;

  useEffect(() => {
    if (!publicDemoConsole || !running || paused) return undefined;
    const interval = window.setInterval(() => {
      setProgress((current) => {
        const next = Math.min(1, current + 0.006);
        if (next >= 1) {
          setRunning(false);
          setComplete(true);
          setEvents((currentEvents) => [
            { time: eventTime(), text: copy.events.completed },
            ...currentEvents,
          ].slice(0, 4));
        }
        return next;
      });
    }, 80);
    return () => window.clearInterval(interval);
  }, [copy.events.completed, paused, running]);

  useEffect(() => {
    if (publicDemoConsole || !simulationExecutionId) return undefined;
    const simulationTerminal = simulationExecutionState
      ? ["verified", "failed", "aborted"].includes(simulationExecutionState)
      : false;
    if (simulationTerminal && (simulationExecutionState !== "verified" || runtimeSessionTerminal)) return undefined;
    let cancelled = false;
    const executionId = simulationExecutionId;
    const refresh = async () => {
      let latest: AutonomySimulationExecution;
      try {
        latest = await apiClient.getAutonomySimulationExecution(executionId);
      } catch {
        if (!cancelled) {
          setRunning(false);
          setCompileError(copy.compileFailed);
        }
        return;
      }
      if (cancelled) return;
      setSimulationExecution(latest);
      setProgress(latest.progress);
      try {
        const liveRuntime = await apiClient.getAutonomyRuntimeSession(latest.runtime_session_id);
        if (!cancelled) {
          setRuntimeSession(liveRuntime);
          setPaused(liveRuntime.phase === "holding");
        }
      } catch {
        // The execution stream remains authoritative for motion telemetry. A
        // transient runtime read failure is retried on the next polling cycle.
      }
      if (latest.state === "verified" && !simulationTerminalHandled.current) {
        simulationTerminalHandled.current = true;
        setRunning(false);
        setComplete(true);
        appendEvent(copy.events.completed);
      } else if (["failed", "aborted"].includes(latest.state) && !simulationTerminalHandled.current) {
        simulationTerminalHandled.current = true;
        setRunning(false);
        setComplete(false);
        setCompileError(latest.abort_reason ? `${copy.compileFailed} ${latest.abort_reason}` : copy.compileFailed);
      }
      if (["verified", "failed", "aborted"].includes(latest.state)) {
        try {
          const sealedRuntime = await apiClient.getAutonomyRuntimeSession(
            latest.runtime_session_id,
          );
          if (!cancelled) setRuntimeSession(sealedRuntime);
        } catch {
          // A verified execution keeps polling until its sealed evidence chain
          // is readable; failed executions already carry their terminal reason.
        }
      }
    };
    const interval = window.setInterval(() => void refresh(), 500);
    void refresh();
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [copy.compileFailed, copy.events.completed, runtimeSessionTerminal, simulationExecutionId, simulationExecutionState]);

  useEffect(() => {
    if (!complete || evidenceReported.current || !onRunCompleted) return;
    if (!publicDemoConsole && (simulationExecution?.state !== "verified" || !runtimeSession?.terminal)) return;
    evidenceReported.current = true;
    const completedAt = new Date().toISOString();
    const sessionId = runtimeSession?.session_id
      ?? (previewRunId.current ??= `preview-run-${crypto.randomUUID()}`);
    onRunCompleted({
      schemaVersion: 2,
      id: sessionId,
      sessionId,
      contractId: qualification.contract.contract_id,
      completedAt,
      executionTarget: target,
      source: runtimeSession ? "backend" : "preview",
      evidenceChainHead: runtimeSession?.evidence_chain_head
        ?? simulationExecution?.mission_evidence_sha256
        ?? "preview-only-no-signed-evidence-chain",
      observationCount: runtimeSession?.observation_count ?? Number(simulationExecution?.mission_evidence?.pose_sample_count ?? 0),
      missionIntent: workspace?.mission.intent ?? command,
      aircraftName: workspace?.aircraft.name ?? "Default preview aircraft",
      mapName: workspace?.mapPack.name ?? qualification.scene.name,
      aircraftVersion: workspace?.aircraft.version ?? 1,
      mapVersion: workspace?.mapPack.version ?? 1,
      taskGraphRevision: activeTaskGraph.revision,
      decisionCount: runtimeSession?.decision_events.length ?? events.length,
      trackedEntityCount: runtimeSession
        ? new Set(runtimeSession.decision_events.flatMap((event) => event.entity_ids)).size
        : (obstacleInjected ? 1 : 0),
    });
  }, [activeTaskGraph.revision, command, complete, events.length, obstacleInjected, onRunCompleted, qualification.contract.contract_id, qualification.scene.name, runtimeSession, simulationExecution, target, workspace?.aircraft.name, workspace?.aircraft.version, workspace?.mapPack.name, workspace?.mapPack.version, workspace?.mission.intent]);

  useEffect(() => {
    stopActiveSimulation("Autonomy mission contract changed while the simulation was active.");
    compileGeneration.current += 1;
    launchGeneration.current += 1;
    setCompileResult(null);
    setCompileSource("preview");
    setCompileError(null);
    setPlanned(false);
    setPlanning(false);
    setRunning(false);
    setLaunching(false);
    setComplete(false);
    setProgress(0);
    setRuntimeSession(null);
    setSimulationExecution(null);
    authorizedCompileRequest.current = null;
    runtimeRequestId.current = null;
    simulationExecutionRequestId.current = null;
    simulationTerminalHandled.current = false;
    evidenceReported.current = false;
    previewRunId.current = null;
    runtimeWorkspaceUpdateIntent.current = null;
  }, [compileRequest, stopActiveSimulation]);

  const appendEvent = (text: string) => {
    setEvents((current) => [{ time: eventTime(), text }, ...current].slice(0, 4));
  };

  const chooseMission = (id: MissionId) => {
    setMissionId(id);
    setCommand(promptForMission(id, chinese));
    setCompileResult(null);
    setPlanned(false);
    setPlanning(false);
    setRunning(false);
    setPaused(false);
    setComplete(false);
    setProgress(0);
    setObstacleInjected(false);
    setDynamicEntityActive(false);
    setEvents([{ time: eventTime(), text: copy.events.ready }]);
  };

  const planTrajectory = async () => {
    if (!workspaceAircraftQualified) {
      setCompileResult(null);
      setCompileError(copy.aircraftUnavailable);
      setPlanned(false);
      return;
    }
    if (!workspaceMapQualified) {
      setCompileResult(null);
      setCompileError(copy.mapUnavailable);
      setPlanned(false);
      return;
    }
    const generation = ++compileGeneration.current;
    const sourceRequest = compileRequest;
    let submittedRequest = sourceRequest;
    previewRunId.current = null;
    evidenceReported.current = false;
    setPlanning(true);
    setCompileError(null);
    setRunning(false);
    setPaused(false);
    setComplete(false);
    setProgress(0);
    try {
      let result: AutonomyCompileResponse;
      let source: "backend" | "preview";
      if (publicDemoConsole) {
        result = createLocalAutonomyPreview(missionId, submittedRequest);
        source = "preview";
      } else {
        if (!workspace) throw new Error("Qualified autonomy workspace required.");
        const harnessRequest = autonomyHarnessRequest(
          edition,
          workspace,
          submittedRequest.natural_language,
        );
        const inspection = await apiClient.inspectAutonomyHarness(harnessRequest);
        if (!inspection.planning_ready) throw new Error("Autonomy asset gate blocked.");
        submittedRequest = {
          ...submittedRequest,
          asset_context: {
            schema_version: "dronedream.autonomy.compile-assets.v1",
            harness_context_sha256: inspection.context_sha256,
            aircraft: harnessRequest.aircraft,
            map_pack: harnessRequest.map_pack,
            planner_binding: workspace.mission.compiledPlan?.plannerBinding ?? null,
          },
        };
        result = await apiClient.compileAutonomyMission(submittedRequest);
        source = "backend";
      }
      if (
        generation !== compileGeneration.current
        || latestCompileRequest.current !== sourceRequest
      ) return;
      setCompileResult(result);
      setCompileSource(source);
      authorizedCompileRequest.current = submittedRequest;
      setPlanned(true);
      appendEvent(copy.events.planned);
    } catch {
      if (
        generation !== compileGeneration.current
        || latestCompileRequest.current !== sourceRequest
      ) return;
      setCompileResult(null);
      authorizedCompileRequest.current = null;
      setCompileSource("preview");
      setCompileError(copy.compileFailed);
      setPlanned(false);
    } finally {
      if (generation === compileGeneration.current) setPlanning(false);
    }
  };

  const toggleFlight = async () => {
    if (!planned || complete || launching) return;
    if (!running) {
      if (publicDemoConsole) {
        previewRunId.current ??= `preview-run-${crypto.randomUUID()}`;
      } else {
        const generation = ++launchGeneration.current;
        setLaunching(true);
        try {
          runtimeRequestId.current ??= crypto.randomUUID();
          simulationExecutionRequestId.current ??= crypto.randomUUID();
          const runtimeMission = authorizedCompileRequest.current;
          if (!runtimeMission) throw new Error("Qualified mission contract required.");
          const plannerArtifactSha256 = runtimeMission.asset_context?.planner_binding?.artifact_sha256;
          if (!plannerArtifactSha256) throw new Error("Model planner artifact binding required.");
          const created = runtimeSession ?? await apiClient.createAutonomyRuntimeSession(
            runtimeMission,
            runtimeRequestId.current,
          );
          if (generation !== launchGeneration.current) {
            if (!created.terminal) {
              await Promise.allSettled([
                apiClient.stopAutonomyRuntimeSession(
                  created.session_id,
                  "abort",
                  "Launch was cancelled before simulator startup.",
                ),
              ]);
            }
            return;
          }
          setRuntimeSession(created);
          const execution = await apiClient.startAutonomySimulationExecution(
            created.session_id,
            created.contract_id,
            plannerArtifactSha256,
            simulationExecutionRequestId.current,
          );
          if (generation !== launchGeneration.current) {
            await Promise.allSettled([
              apiClient.abortAutonomySimulationExecution(
                execution.execution_id,
                "Launch was cancelled before the simulator response was applied.",
              ),
              ...(!created.terminal
                ? [apiClient.stopAutonomyRuntimeSession(
                    created.session_id,
                    "abort",
                    "Launch was cancelled before the simulator response was applied.",
                  )]
                : []),
            ]);
            return;
          }
          simulationTerminalHandled.current = false;
          setSimulationExecution(execution);
        } catch {
          if (generation === launchGeneration.current) setCompileError(copy.compileFailed);
          return;
        } finally {
          if (generation === launchGeneration.current) setLaunching(false);
        }
        if (generation !== launchGeneration.current) return;
      }
      setRunning(true);
      setPaused(false);
      appendEvent(copy.events.launched);
      return;
    }
    if (!publicDemoConsole) return;
    setPaused((current) => {
      appendEvent(current ? copy.events.launched : copy.events.paused);
      return !current;
    });
  };

  const resetMission = () => {
    launchGeneration.current += 1;
    stopActiveSimulation("Operator reset the mission workspace.");
    setRunning(false);
    setLaunching(false);
    setPaused(false);
    setComplete(false);
    setProgress(0);
    setObstacleInjected(false);
    setDynamicEntityActive(false);
    setRuntimeSession(null);
    setSimulationExecution(null);
    setRuntimeInstruction("");
    setRuntimeReplanning(false);
    setRuntimeReplanError(null);
    runtimeRequestId.current = null;
    simulationExecutionRequestId.current = null;
    simulationTerminalHandled.current = false;
    evidenceReported.current = false;
    previewRunId.current = null;
    setEvents([{ time: eventTime(), text: planned ? copy.events.planned : copy.events.ready }]);
  };

  const submitRuntimeInstruction = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const instruction = runtimeInstruction.trim();
    const activeRuntime = runtimeSessionRef.current;
    if (
      publicDemoConsole
      || !instruction
      || instruction.length > 2_000
      || !activeRuntime
      || activeRuntime.terminal
      || !workspace
      || !onWorkspaceChange
      || runtimeReplanning
    ) return;

    setRuntimeReplanning(true);
    setRuntimeReplanError(null);
    const interruptionRequestId = crypto.randomUUID();
    try {
      // Flight-affecting messages always enter a safe hold before any model or
      // harness call. The language-model latency therefore cannot let the old
      // task graph continue into a pickup, wall, doorway, or landing transition.
      const held = await apiClient.interruptAutonomyRuntimeSession(
        activeRuntime.session_id,
        { client_request_id: interruptionRequestId, instruction },
      );
      const interruption = held.interruption;
      if (!interruption || interruption.state !== "holding_pending_interpretation") {
        throw new Error("Runtime did not return a verifiable interruption receipt.");
      }
      setRuntimeSession(held);
      setPaused(true);
      appendEvent(copy.runtimeHolding);

      if (!planningModel) {
        throw new Error("No planning model is bound to this task conversation.");
      }
      const turnId = crypto.randomUUID();
      const conversationId = workspace.mission.conversationId ?? workspace.mission.id;
      const prefix = chinese ? "\n执行中调整：" : "\nIn-flight update: ";
      const revisedIntent = `${workspace.mission.intent.slice(
        0,
        Math.max(0, 2_000 - prefix.length - instruction.length),
      )}${prefix}${instruction}`;
      const submittedAt = new Date().toISOString();
      const userMessage: AutonomyConversationMessage = {
        id: `user-${turnId}`,
        role: "user",
        content: instruction,
        createdAt: submittedAt,
        planContractId: null,
      };
      const pendingWorkspace: AutonomyWorkspaceState = {
        ...workspace,
        mission: {
          ...workspace.mission,
          intent: revisedIntent,
          conversationId,
          messages: [...workspace.mission.messages, userMessage].slice(-100),
          updatedAt: submittedAt,
        },
      };
      runtimeWorkspaceUpdateIntent.current = revisedIntent;
      onWorkspaceChange(pendingWorkspace);
      appendEvent(copy.runtimePlanning);

      const planning = await planAutonomyMission({
        edition,
        workspace: pendingWorkspace,
        intent: revisedIntent,
        instruction,
        conversationId,
        turnId,
        chinese,
        selectedModel: planningModel,
        accountId,
        publicDemo: false,
        requestPurpose: "runtime_replan",
        runtimeContext: {
          schema_version: "dronedream.autonomy.runtime-replan-context.v1",
          session_id: held.session_id,
          contract_id: held.contract_id,
          phase: held.phase,
          mission_revision: held.mission_revision,
          task_graph_revision: held.task_graph.revision,
          task_graph: held.task_graph,
          interruption,
          simulation_execution: simulationExecutionRef.current
            ? {
                execution_id: simulationExecutionRef.current.execution_id,
                state: simulationExecutionRef.current.state,
                phase: simulationExecutionRef.current.phase,
                progress: simulationExecutionRef.current.progress,
                vehicle_envelope_center_world_enu_m:
                  simulationExecutionRef.current.vehicle_envelope_center_world_enu_m,
                vehicle_speed_m_s: simulationExecutionRef.current.vehicle_speed_m_s,
                payload_attached: simulationExecutionRef.current.payload_attached,
              }
            : null,
        },
      });
      if (!planning.compileRequest || !planning.compileResult || !planning.compiledPlan) {
        throw new Error("The replacement plan did not pass the planning and compilation gates.");
      }
      const applied = await apiClient.applyAutonomyRuntimeReplan(
        held.session_id,
        {
          interruption_id: interruption.interruption_id,
          expected_task_graph_revision: interruption.expected_task_graph_revision,
          client_request_id: crypto.randomUUID(),
          operator_confirmed: true,
          mission: planning.compileRequest,
        },
      );
      const updatedAt = new Date().toISOString();
      const assistantMessage: AutonomyConversationMessage = {
        id: `assistant-${turnId}`,
        role: "assistant",
        content: planning.planningBrief || copy.runtimeApplied,
        createdAt: updatedAt,
        planContractId: planning.compiledPlan.contractId,
      };
      onWorkspaceChange({
        ...pendingWorkspace,
        mission: {
          ...pendingWorkspace.mission,
          planningModel,
          planningBrief: planning.planningBrief,
          planningRunId: planning.planningRunId,
          messages: [...pendingWorkspace.mission.messages, assistantMessage].slice(-100),
          compiledPlan: planning.compiledPlan,
          updatedAt,
        },
      });
      authorizedCompileRequest.current = planning.compileRequest;
      setCompileResult(planning.compileResult);
      setCompileSource("backend");
      setPlanned(true);
      setRuntimeSession(applied);
      setPaused(false);
      setRuntimeInstruction("");
      appendEvent(copy.runtimeApplied);
    } catch (reason) {
      setPaused(true);
      setRuntimeReplanError(localeSafeError(reason, chinese ? "zh-CN" : "en", {
        zh: copy.runtimeReplanFailed,
        en: copy.runtimeReplanFailed,
      }));
      appendEvent(copy.runtimeReplanFailed);
    } finally {
      setRuntimeReplanning(false);
    }
  };

  const injectObstacle = () => {
    if (!planned || obstacleInjected || complete) return;
    setObstacleInjected(true);
    setDynamicEntityActive(true);
    if (dynamicEntityTimer.current !== null) window.clearTimeout(dynamicEntityTimer.current);
    dynamicEntityTimer.current = window.setTimeout(() => {
      setDynamicEntityActive(false);
      appendEvent(chinese ? "人员已离开安全走廊，局部路线通过验证并恢复任务。" : "Person cleared the corridor; the repaired local route was accepted and the mission resumed.");
    }, 2_400);
    appendEvent(copy.events.obstacle);
  };

  useEffect(() => () => {
    if (dynamicEntityTimer.current !== null) window.clearTimeout(dynamicEntityTimer.current);
  }, []);

  return (
    <div className={`autonomy-lab-page${embedded ? " is-embedded" : ""}`}>
      {!embedded ? <header className="autonomy-hero">
        <div>
          <span className="autonomy-kicker">{editionLabel} · {copy.kicker}</span>
          <div className="autonomy-title-line">
            <h1>{copy.title}</h1>
            <span><Sparkles aria-hidden="true" />{copy.simulationOnly}</span>
            <span className="autonomy-independent">{copy.independent}</span>
          </div>
        </div>
        <div className={`autonomy-flight-status ${complete ? "is-complete" : running ? "is-running" : ""}`}>
          <span />
          {complete ? copy.completed : running ? copy.running : planned ? copy.planned : copy.ready}
        </div>
      </header> : null}

      {!embedded ? <section className="autonomy-command-center" data-execution-target={target}>
        <div className="autonomy-command-input autonomy-intent-contract">
          <div className="autonomy-command-heading">
            <span><MessageSquareText aria-hidden="true" /><strong>{copy.intentSource}</strong></span>
          </div>
          <p className="autonomy-intent-readout">{command}</p>
          <div className="autonomy-command-actions">
            <div className="autonomy-target-switch" role="group" aria-label={copy.executionTarget}>
              {(Object.keys(copy.targets) as AutonomyExecutionTarget[]).map((candidate) => (
                <button
                  key={candidate}
                  type="button"
                  className={target === candidate ? "is-active" : ""}
                  aria-pressed={target === candidate}
                  disabled={planning || launching || running || Boolean(runtimeSession && !runtimeSession.terminal)}
                  onClick={() => setTarget(candidate)}
                >
                  {candidate === "simulation" ? <Cpu aria-hidden="true" /> : candidate === "hitl" ? <FileCheck2 aria-hidden="true" /> : <Navigation2 aria-hidden="true" />}
                  {copy.targets[candidate]}
                </button>
              ))}
            </div>
            <span className="autonomy-target-help">{copy.targetHelp[target]}</span>
            <Link className="btn autonomy-edit-in-chat" to="/autonomy">
              <MessageSquareText aria-hidden="true" />{copy.editInChat}
            </Link>
            <button
              className="btn btn-primary autonomy-compile-button"
              type="button"
              disabled={planning || launching || running || command.trim().length < 3}
              onClick={() => void planTrajectory()}
            >
              {planning ? <RefreshCcw className="is-spinning" aria-hidden="true" /> : <Sparkles aria-hidden="true" />}
              {planning ? copy.compilingCommand : copy.compileCommand}
            </button>
          </div>
          {compileError ? (
            <div className="autonomy-compile-error" role="alert">
              <AlertTriangle aria-hidden="true" />
              <span>{compileError}</span>
            </div>
          ) : null}
        </div>

        <div className="autonomy-contract-summary">
          <header>
            <span><FileCheck2 aria-hidden="true" /><strong>{copy.contract}</strong></span>
            <em className={compileSource === "backend" ? "is-backend" : ""}>
              {compileSource === "backend" ? copy.sourceBackend : copy.sourcePreview}
            </em>
          </header>
          <code>{qualification.contract.contract_id}</code>
          <dl>
            <div>
              <dt>{qualification.feasible ? <BadgeCheck aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}{qualification.feasible ? copy.feasible : copy.blocked}</dt>
              <dd>{qualification.metrics.route_length_m.toFixed(1)} m · {qualification.metrics.minimum_clearance_m.toFixed(2)} m</dd>
            </div>
            <div><dt><Weight aria-hidden="true" />{copy.loadedMass}</dt><dd>{qualification.metrics.post_pickup_mass_kg.toFixed(2)} kg</dd></div>
            <div><dt><ShieldCheck aria-hidden="true" />{copy.thrustMargin}</dt><dd>{qualification.metrics.post_pickup_thrust_to_weight.toFixed(2)}</dd></div>
            <div className={qualification.execution_policy.can_execute ? "is-ready" : "is-denied"}>
              <dt>{qualification.execution_policy.can_execute ? <BadgeCheck aria-hidden="true" /> : <LockKeyhole aria-hidden="true" />}{qualification.execution_policy.can_execute ? copy.feasible : copy.blocked}</dt>
              <dd>{localizedLabel(
                ADAPTER_LABELS[qualification.execution_policy.adapter],
                qualification.execution_policy.adapter,
                chinese,
              )}</dd>
            </div>
          </dl>
        </div>
      </section> : null}

      <section className="autonomy-workspace">
        {!embedded ? <aside className="autonomy-panel autonomy-config-panel">
          <div className="autonomy-panel-heading">
            <div><Route aria-hidden="true" /><span>{copy.mission}</span></div>
            <code>MISSION-01</code>
          </div>
          <div className="autonomy-mission-list">
            {missions.map((candidate) => {
              const Icon = candidate.icon;
              return (
                <button
                  key={candidate.id}
                  type="button"
                  className={candidate.id === missionId ? "is-active" : ""}
                  disabled={planning || launching || running || Boolean(runtimeSession && !runtimeSession.terminal)}
                  onClick={() => chooseMission(candidate.id)}
                >
                  <Icon aria-hidden="true" />
                  <span><strong>{candidate.name}</strong><small>{candidate.description}</small></span>
                  {candidate.id === missionId ? <Check aria-hidden="true" /> : null}
                </button>
              );
            })}
          </div>

          <div className="autonomy-config-section">
            <h2><Radar aria-hidden="true" />{copy.perception}</h2>
            <div className="autonomy-mode-switch" role="group" aria-label={copy.perception}>
              {(Object.keys(copy.modes) as PerceptionMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={perception === mode ? "is-active" : ""}
                  disabled={planning || launching || running || Boolean(runtimeSession && !runtimeSession.terminal)}
                  onClick={() => setPerception(mode)}
                >
                  {mode === "vision" ? <Camera aria-hidden="true" /> : mode === "map" ? <Map aria-hidden="true" /> : <Navigation2 aria-hidden="true" />}
                  {copy.modes[mode]}
                </button>
              ))}
            </div>
          </div>

          <div className="autonomy-config-section autonomy-payload-control">
            <h2><Weight aria-hidden="true" />{copy.payload}</h2>
            <label>
              <input
                type="range"
                min="0"
                max="1.2"
                step="0.05"
                value={pickupPayloadKg}
                disabled={planning || launching || running || Boolean(runtimeSession && !runtimeSession.terminal)}
                onChange={(event) => setPickupPayloadKg(Number(event.target.value))}
              />
              <strong>{pickupPayloadKg.toFixed(2)} kg</strong>
            </label>
          </div>

          <div className="autonomy-config-section autonomy-checkpoints">
            <h2><Waypoints aria-hidden="true" />{copy.taskFlow}</h2>
            <ol>
              <li><span>S</span><strong>{copy.start}</strong></li>
              <li><span>1</span><strong>{missionId === "coffee" ? copy.destination : copy.via}</strong></li>
              <li><span>G</span><strong>{missionId === "coffee" ? copy.returnHome : copy.destination}</strong></li>
            </ol>
          </div>

          <button className="btn btn-primary autonomy-plan-button" type="button" onClick={() => void planTrajectory()} disabled={planning || launching || running || Boolean(runtimeSession && !runtimeSession.terminal) || command.trim().length < 3}>
            {planning ? <RefreshCcw className="is-spinning" aria-hidden="true" /> : <Route aria-hidden="true" />}
            {planning ? copy.planning : planned ? copy.replan : copy.plan}
          </button>
        </aside> : null}

        <section className="autonomy-panel autonomy-map-panel">
          <div className="autonomy-panel-heading autonomy-map-heading">
            <div><Map aria-hidden="true" /><span>{workspace?.mapPack.name ?? copy.environment}</span></div>
            <span className="autonomy-world-state">{perception === "vision" ? copy.unknown : copy.mapped}</span>
          </div>
          <div className="autonomy-map-stage">
            <AutonomyWorld3D
              missionId={missionId}
              progress={progress}
              planned={planned}
              obstacleInjected={obstacleInjected}
              dynamicEntityActive={dynamicEntityActive}
              perception={perception}
              mapName={workspace?.mapPack.name ?? mission.name}
              vehicleEnvelopeCenterWorldEnuM={simulationExecution?.vehicle_envelope_center_world_enu_m}
            />

            <div className="autonomy-camera-card">
              <div><Camera aria-hidden="true" /><span>{copy.cameraFeed}</span><i /></div>
              <div className="autonomy-camera-scene">
                <span className="autonomy-camera-horizon" />
                <span className="autonomy-camera-box"><small>{perception === "map"
                  ? (chinese ? "地图 + GPS" : "MAP + GPS")
                  : (chinese ? "传感器未安装" : "SENSOR NOT INSTALLED")}</small></span>
                <span className="autonomy-camera-depth" />
              </div>
            </div>
          </div>
          <div className="autonomy-map-controls">
            {embedded ? <div className="autonomy-target-switch autonomy-live-target-switch" role="group" aria-label={copy.executionTarget}>
              {(Object.keys(copy.targets) as AutonomyExecutionTarget[]).map((candidate) => <button key={candidate} type="button" className={target === candidate ? "is-active" : ""} aria-pressed={target === candidate} disabled={planning || launching || running || Boolean(runtimeSession && !runtimeSession.terminal)} onClick={() => setTarget(candidate)}>{copy.targets[candidate]}</button>)}
            </div> : null}
            {embedded ? <button className="btn" type="button" onClick={() => void planTrajectory()} disabled={planning || launching || running || command.trim().length < 3}>
              {planning ? <RefreshCcw className="is-spinning" aria-hidden="true" /> : <Route aria-hidden="true" />}
              {planning ? copy.planning : planned ? copy.replan : copy.plan}
            </button> : null}
            <button className="btn btn-primary" type="button" disabled={launching || (!publicDemoConsole && running) || !planned || complete || !qualification.execution_policy.can_execute} onClick={() => void toggleFlight()}>
              {!qualification.execution_policy.can_execute ? <LockKeyhole aria-hidden="true" /> : running && !paused ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
              {running ? publicDemoConsole ? paused ? copy.resume : copy.pause : copy.running : copy.run}
            </button>
            <button className="btn" type="button" onClick={resetMission}><RefreshCcw aria-hidden="true" />{copy.reset}</button>
            <button className="btn autonomy-inject-button" type="button" disabled={!publicDemoConsole || !planned || obstacleInjected || complete} onClick={injectObstacle}>
              <Sparkles aria-hidden="true" />{copy.inject}
            </button>
            <div className="autonomy-progress"><span><i style={{ width: `${Math.round(progress * 100)}%` }} /></span><strong>{Math.round(progress * 100)}%</strong></div>
          </div>
          {embedded && runtimeSession && !runtimeSession.terminal ? (
            <form className="autonomy-runtime-composer" onSubmit={(event) => void submitRuntimeInstruction(event)}>
              <div>
                <strong>{copy.runtimeInstruction}</strong>
                <span>{runtimeReplanning
                  ? copy.runtimePlanning
                  : runtimeSession.phase === "holding"
                    ? copy.runtimeHolding
                    : copy.running}</span>
              </div>
              <label>
                <textarea
                  value={runtimeInstruction}
                  maxLength={2_000}
                  rows={1}
                  disabled={runtimeReplanning}
                  placeholder={copy.runtimeInstructionPlaceholder}
                  aria-label={copy.runtimeInstruction}
                  onChange={(event) => setRuntimeInstruction(event.target.value)}
                />
                <button
                  type="submit"
                  aria-label={copy.sendRuntimeInstruction}
                  title={copy.sendRuntimeInstruction}
                  disabled={runtimeReplanning || !runtimeInstruction.trim()}
                >
                  {runtimeReplanning ? <RefreshCcw className="is-spinning" aria-hidden="true" /> : <ArrowUp aria-hidden="true" />}
                </button>
              </label>
              {runtimeReplanError ? <p role="alert">{runtimeReplanError}</p> : null}
            </form>
          ) : null}
        </section>

        <aside className="autonomy-panel autonomy-brain-panel">
          <div className="autonomy-panel-heading">
            <div><BrainCircuit aria-hidden="true" /><span>{copy.brain}</span></div>
            <span className="autonomy-brain-rate">{chinese ? "20 Hz PX4 设定点" : "20 Hz PX4 setpoints"}</span>
          </div>
          {!embedded ? <div className="autonomy-task-graph-heading">
            <span>{chinese ? "任务图" : "GRAPH"} · {activeTaskGraph.change_reason}</span>
            <button type="button" onClick={() => setTaskGraphView((current) => current === "summary" ? "engineering" : "summary")}>
              {taskGraphView === "summary" ? (chinese ? "工程详情" : "Engineering") : (chinese ? "简洁视图" : "Summary")}
            </button>
          </div> : null}
          <ol className={`autonomy-task-graph is-${taskGraphView}`}>
            {(embedded ? embeddedTaskGraphNodes(activeTaskGraph) : activeTaskGraph.nodes).map((node) => (
              <li key={node.task_id} data-status={node.status} data-source={node.inserted_by}>
                <span>{node.status === "completed" ? <Check aria-hidden="true" /> : activeTaskGraph.nodes.findIndex((candidate) => candidate.task_id === node.task_id) + 1}</span>
                <div>
                  <strong>{node.label}</strong>
                  <small>{embedded
                    ? localizedLabel(TASK_STATUS_LABELS[node.status], node.status, chinese)
                    : `${localizedLabel(TASK_STATUS_LABELS[node.status], node.status, chinese)} · ${localizedLabel(EXECUTOR_LABELS[node.executor], node.executor, chinese)}`}</small>
                  {taskGraphView === "engineering" ? <em>
                    {localizedLabel(RISK_LABELS[node.risk], node.risk, chinese)} · {node.timeout_s}s · {node.max_retries} {chinese ? "次重试" : "retries"} · {localizedLabel(FALLBACK_LABELS[node.fallback], node.fallback, chinese)}
                  </em> : null}
                </div>
              </li>
            ))}
          </ol>

          <div className="autonomy-live-perception">
            <header><h2><Radar aria-hidden="true" />{chinese ? "实时感知" : "Live perception"}</h2><span>{activeEntities.length} {chinese ? "个跟踪实体" : "tracked"}</span></header>
            <div className="autonomy-stream-health">
              {(runtimeSession?.stream_health ?? (publicDemoConsole ? simulatedStreamHealth() : [])).map((stream) => <span key={stream.stream_id} data-status={stream.status}><i />{localizedLabel(STREAM_KIND_LABELS[stream.kind], stream.kind, chinese)}{!embedded ? <small>{stream.rate_hz} Hz · {stream.latency_ms} ms</small> : null}</span>)}
            </div>
            {!embedded ? activeEntities.map((entity) => <article key={entity.track_id}>
              <Radar aria-hidden="true" />
              <span><strong>{localizedLabel(ENTITY_KIND_LABELS[entity.kind], entity.kind, chinese)} · {entity.track_id}</strong><small>{Math.round(entity.confidence * 100)}% · {entity.source_stream} · {entity.velocity_mps.y.toFixed(2)} m/s</small></span>
              <em>{entity.safety_radius_m.toFixed(1)} m</em>
            </article>) : null}
          </div>

          <div className="autonomy-runtime-stack">
            <header>
              <h2><Cpu aria-hidden="true" />{copy.onboardRuntime}</h2>
              <span data-mode={qualification.runtime_profile.mode}>
                {copy.runtimeModes[qualification.runtime_profile.mode]}
              </span>
            </header>
            <ul>
              {qualification.runtime_profile.components.map((component) => (
                <li key={component.id} data-status={component.status}>
                  <i aria-hidden="true" />
                  <strong>{runtimeComponentLabel(component.id, chinese, perception === "map")}</strong>
                  {!embedded ? <small>{component.rate_hz ? `${component.rate_hz} Hz` : "—"}</small> : null}
                </li>
              ))}
            </ul>
            {!embedded ? <code className="autonomy-runtime-receipt">
              {simulationExecution
                ? `${localizedLabel(RUNTIME_PHASE_LABELS[simulationExecution.phase], simulationExecution.phase, chinese)} · ${simulationExecution.execution_id.slice(0, 20)} · ${simulationExecution.planner_artifact_sha256.slice(0, 12)}`
                : runtimeSession
                  ? `${localizedLabel(RUNTIME_PHASE_LABELS[runtimeSession.phase], runtimeSession.phase, chinese)} · ${runtimeSession.session_id.slice(0, 18)} · ${runtimeSession.evidence_chain_head.slice(0, 12)}`
                : copy.runtimeAwaiting}
            </code> : null}
          </div>

          <div className="autonomy-telemetry">
            <h2><ShieldCheck aria-hidden="true" />{copy.telemetry}</h2>
            <dl>
              <div><dt>{copy.distance}</dt><dd>{mission.distance}</dd></div>
              <div><dt>{copy.clearance}</dt><dd>{obstacleInjected ? "0.52 m" : mission.clearance}</dd></div>
              <div><dt>{copy.eta}</dt><dd>{mission.eta}</dd></div>
              <div><dt>{copy.speed}</dt><dd>{liveSpeed}</dd></div>
              <div><dt>{copy.checkpoint}</dt><dd>{nextCheckpoint}</dd></div>
              <div><dt>{copy.confidence}</dt><dd>{confidence}</dd></div>
            </dl>
          </div>

          <div className={`autonomy-safety-gate ${qualification.execution_policy.can_execute ? "is-ready" : "is-denied"}${embedded ? " is-embedded" : ""}`}>
            <h2>{qualification.execution_policy.can_execute ? <BadgeCheck aria-hidden="true" /> : <LockKeyhole aria-hidden="true" />}{copy.safetyGate}</h2>
            <div className="autonomy-safety-readout">
              <span>{copy.signedPacks}</span><strong>{qualification.execution_policy.validated_signed_pack_count}</strong>
            </div>
            {qualification.execution_policy.blockers.length ? (
              <ul>{qualification.execution_policy.blockers.slice(0, embedded ? 2 : 4).map((blocker) => <li key={blocker}>{localizedLabel(BLOCKER_LABELS[blocker], blocker, chinese)}</li>)}</ul>
            ) : <p>{copy.noBlockers}</p>}
          </div>

          {!embedded ? <div className="autonomy-event-log">
            <h2>{copy.eventLog}</h2>
            <ul aria-live="polite">
              {events.map((event, index) => <li key={`${event.time}-${index}`}><time>{event.time}</time><span>{event.text}</span></li>)}
            </ul>
          </div> : null}
        </aside>
      </section>
    </div>
  );
}
