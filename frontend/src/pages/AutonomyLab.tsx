import {
  AlertTriangle,
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
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { apiClient } from "../api/client";
import { BUILD_EDITION, EDITION_IS_FIXED } from "../edition";
import { createLocalAutonomyPreview } from "../features/autonomy/missionAutonomy";
import {
  autonomyAircraftRadiusM,
  isAutonomyAircraftProfileValid,
  type AutonomyAircraftProfile,
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
import { useI18n } from "../i18n/I18nProvider";
import type { InterfaceLocale } from "../i18n/I18nProvider";
import type {
  AutonomyCompileRequest,
  AutonomyCompileResponse,
  AutonomyEdition,
  AutonomyExecutionTarget,
  AutonomyRuntimeSession,
} from "../types/api";

type MissionId = "coffee" | "gates" | "narrow";
type PerceptionMode = "fusion" | "vision" | "map";
type Point = readonly [number, number];

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
  kicker: "MISSION AUTONOMY",
  title: "Mission Autonomy",
  subtitle: "Describe a mission in ordinary language. DroneDream compiles a bounded task contract, validates terrain, payload and dynamics, then qualifies it for simulation before any hardware handoff.",
  simulationOnly: "SHARED AUTONOMY CORE",
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
  cameraFeed: "FRONT RGB-D",
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
  brain: "Autonomy brain",
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
  kicker: "任务级自主飞行",
  title: "智能任务飞行",
  subtitle: "用自然语言描述任务，由 DroneDream 编译受约束任务合同，检查地形、载荷与动力学；真机移交前必须先通过同一合同的仿真资格验证。",
  simulationOnly: "四版本共享自主核心",
  independent: "语言理解 · 确定性安全内核",
  commandTitle: "自然语言任务",
  commandHelp: "模型只负责把意图结构化，不直接输出电机或姿态指令；几何与物理安全检查不可绕过。",
  compileCommand: "编译并验证",
  compilingCommand: "正在检查任务…",
  compileFailed: "权威后端未批准本次请求。请检查运行时连接和任务输入后重试。",
  mapUnavailable: "地图包尚未验证。请先完成校准并绑定已验证的编译场景。",
  aircraftUnavailable: "机型包络超出编译器合同。请检查质量、推力、电量预留和规划半径。",
  intentSource: "来自 Tuning Chat 的任务意图",
  editInChat: "返回 Tuning Chat 修改",
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
  cameraFeed: "前视 RGB-D",
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
  brain: "自主飞行大脑",
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
  events: {
    ready: "任务已载入，等待生成航迹。",
    planned: "安全走廊与平滑航迹已生成。",
    launched: "仿真任务已起飞，局部安全环正在工作。",
    paused: "航迹跟踪已停在当前设定点。",
    obstacle: "检测到新障碍，已局部修复航迹且未改变任务目标。",
    completed: "全部检查点已通过，任务流程完成。",
  },
};

const COPY_BY_LOCALE: Partial<Record<InterfaceLocale, AutonomyCopy>> = {
  en: EN_COPY,
  "zh-CN": ZH_COPY,
  "zh-TW": {
    ...ZH_COPY,
    title: "自主飛行",
    subtitle: "只給無人機終點、攝影機畫面或一張地圖，由它生成可飛航跡、平穩執行，並在環境變化時即時重規劃。",
    independent: "獨立於控制參數調校",
  },
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
  coffee: "stairwell-coffee-return",
  gates: "forest-gate-inspection",
  narrow: "service-corridor-dock",
};

const MISSION_BY_SCENE_ID = Object.fromEntries(
  Object.entries(SCENE_ID_BY_MISSION).map(([missionId, sceneId]) => [sceneId, missionId as MissionId]),
) as Record<string, MissionId>;

const DEFAULT_VEHICLE: AutonomyCompileRequest["vehicle"] = {
  dry_mass_kg: 1.55,
  launch_payload_kg: 0.10,
  pickup_payload_kg: 0.35,
  max_takeoff_mass_kg: 2.60,
  max_total_thrust_n: 39.0,
  radius_m: 0.28,
  max_speed_mps: 1.30,
  max_acceleration_mps2: 3.0,
  reserve_battery_percent: 30,
};

function missionForWorkspace(workspace?: AutonomyWorkspaceState): MissionId {
  if (!workspace) return "coffee";
  const boundMission = workspace.mapPack.compilerSceneId
    ? MISSION_BY_SCENE_ID[workspace.mapPack.compilerSceneId]
    : undefined;
  if (boundMission) return boundMission;
  const intent = workspace.mission.intent.toLowerCase();
  if (workspace.mapPack.semanticLayers.includes("gates") || /\bgates?\b|圆环|穿门/u.test(intent)) return "gates";
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
  const pickupCapacityKg = Math.max(0, payloadMarginKg - launchPayloadKg);
  return {
    ...DEFAULT_VEHICLE,
    dry_mass_kg: aircraft.dryMassKg,
    launch_payload_kg: launchPayloadKg,
    pickup_payload_kg: Math.min(DEFAULT_VEHICLE.pickup_payload_kg, pickupCapacityKg),
    max_takeoff_mass_kg: aircraft.maximumTakeoffMassKg,
    max_total_thrust_n: aircraft.maximumThrustN,
    radius_m: autonomyAircraftRadiusM(aircraft),
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
    if (missionId === "gates") return "仅使用实时视觉，从起点穿过树林中的三个圆门中心，遇到新障碍时局部重规划，最后在终点平稳降落。";
    if (missionId === "narrow") return "从服务走廊起飞，绕过盲角、竖直告示牌和狭窄障碍，到指定停靠点精准降落。";
    return "从三楼办公室起飞，穿过狭窄楼梯到一楼室外，避开树、建筑物、告示牌和立柱，取到 0.35 kg 咖啡后重新检查动力学并安全返回原起点。";
  }
  if (missionId === "gates") return "Using live vision only, fly from the start through the centers of three forest gates, locally replan around surprises, and land smoothly at the goal.";
  if (missionId === "narrow") return "Launch in the service corridor, avoid blind corners, vertical signs and tight obstacles, then dock precisely at the target.";
  return "Launch from the third-floor office, descend the narrow stairs, avoid trees, buildings, signs and poles, pick up a 0.35 kg coffee, recheck dynamics, and return safely to the launch point.";
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

function pathData(points: readonly Point[]) {
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x} ${y}`).join(" ");
}

function eventTime() {
  return new Intl.DateTimeFormat(undefined, { minute: "2-digit", second: "2-digit" }).format(new Date());
}

function runtimeComponentLabel(
  id: AutonomyCompileResponse["runtime_profile"]["components"][number]["id"],
  chinese: boolean,
): string {
  const labels = chinese ? {
    mission_executive: "任务状态机",
    perception_vio_slam: "感知 / VIO / SLAM",
    world_model: "实时世界模型",
    global_planner: "全局规划器",
    local_planner: "局部重规划",
    trajectory_tracker: "航迹跟踪器",
    px4_bridge: "PX4 控制桥",
    safety_supervisor: "独立安全监督",
    evidence_recorder: "证据记录器",
  } : {
    mission_executive: "Mission executive",
    perception_vio_slam: "Perception / VIO / SLAM",
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

export function AutonomyLab({
  embedded = false,
  onRunCompleted,
  workspace,
}: {
  embedded?: boolean;
  onRunCompleted?: (record: AutonomyEvidenceRecord) => void;
  workspace?: AutonomyWorkspaceState;
} = {}) {
  const { interfaceLocale } = useI18n();
  const copy = COPY_BY_LOCALE[interfaceLocale] ?? EN_COPY;
  const chinese = interfaceLocale === "zh-CN" || interfaceLocale === "zh-TW";
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
  const [planned, setPlanned] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [running, setRunning] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [paused, setPaused] = useState(false);
  const [complete, setComplete] = useState(false);
  const [progress, setProgress] = useState(0);
  const [obstacleInjected, setObstacleInjected] = useState(false);
  const [runtimeSession, setRuntimeSession] = useState<AutonomyRuntimeSession | null>(null);
  const runtimeRequestId = useRef<string | null>(null);
  const runtimeSequence = useRef(0);
  const runtimeObservationPending = useRef(false);
  const runtimeTerminalSent = useRef(false);
  const evidenceReported = useRef(false);
  const previewRunId = useRef<string | null>(null);
  const workspaceBindingApplied = useRef<string | null>(null);
  const progressRef = useRef(0);
  const dronePositionRef = useRef<Point>([0, 0]);
  const [events, setEvents] = useState(() => [{ time: eventTime(), text: copy.events.ready }]);
  const workspaceBindingKey = workspace
    ? `${workspace.aircraft.updatedAt}:${workspace.mapPack.updatedAt}:${workspace.mission.updatedAt}:${workspace.mission.intent}`
    : "standalone";

  useEffect(() => {
    if (workspaceBindingApplied.current === workspaceBindingKey) return;
    workspaceBindingApplied.current = workspaceBindingKey;
    if (!workspace) {
      consumeAutonomyHandoff();
      return;
    }
    setCommand(workspace.mission.intent);
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

  useEffect(() => {
    setTarget(defaultTarget(edition));
    setCompileResult(null);
    setPlanned(false);
  }, [edition]);

  const missions = useMemo(() => Object.values(BASE_MISSIONS).map((base) => ({
    ...base,
    ...copy.missions[base.id],
  })), [copy]);
  const mission = missions.find(({ id }) => id === missionId) ?? missions[0];
  const hasWorkspace = workspace !== undefined;
  const workspaceCompilerSceneId = workspace?.mapPack.compilerSceneId;
  const workspaceMapQualified = !hasWorkspace
    || (workspace?.mapPack.calibrated === true && Boolean(workspaceCompilerSceneId));
  const workspaceAircraftQualified = !workspace
    || isAutonomyAircraftProfileValid(workspace.aircraft);
  const compileRequest = useMemo<AutonomyCompileRequest>(() => ({
    edition,
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
  }), [chinese, command, edition, hasWorkspace, missionId, perception, pickupPayloadKg, target, workspaceCompilerSceneId, workspaceVehicle]);
  const latestCompileRequest = useRef(compileRequest);
  latestCompileRequest.current = compileRequest;
  const provisionalResult = useMemo(
    () => createLocalAutonomyPreview(missionId, compileRequest),
    [compileRequest, missionId],
  );
  const qualification = compileResult ?? provisionalResult;
  const editionLabel = ({
    universal: "UNIVERSAL",
    sim: "SIM",
    lab: "LAB",
    field: "FIELD",
  } as const)[edition];
  const activePoints = obstacleInjected ? mission.replanPoints : mission.points;
  const [droneX, droneY] = interpolatePath(activePoints, progress);
  progressRef.current = progress;
  dronePositionRef.current = [droneX, droneY];
  const runtimeSessionId = runtimeSession?.session_id ?? null;
  const activeStage = complete ? 4 : !planned ? 0 : !running ? 2 : obstacleInjected ? 4 : progress < 0.18 ? 0 : progress < 0.36 ? 1 : progress < 0.56 ? 2 : 3;
  const nextCheckpoint = missionId === "coffee"
    ? progress < 0.42 ? copy.destination : progress < 0.94 ? copy.returnHome : copy.start
    : progress < 0.55 ? copy.via : copy.destination;
  const liveSpeed = running && !paused ? `${(2.1 + Math.sin(progress * 18) * 0.35).toFixed(1)} m/s` : "0.0 m/s";
  const confidence = perception === "map" ? "100%" : `${Math.round(86 + progress * 10)}%`;

  useEffect(() => {
    if (!running || paused) return undefined;
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
    if (!running || !runtimeSessionId || publicDemoConsole) return undefined;
    const sessionId = runtimeSessionId;
    const interval = window.setInterval(() => {
      if (runtimeObservationPending.current) return;
      runtimeObservationPending.current = true;
      const sequence = ++runtimeSequence.current;
      const currentProgress = progressRef.current;
      const [currentX, currentY] = dronePositionRef.current;
      void apiClient.ingestAutonomyRuntimeObservation(sessionId, {
        sequence,
        monotonic_ms: Math.max(1, Math.round(performance.now())),
        armed: true,
        landed: false,
        position_m: { x: currentX / 20, y: currentY / 20, z: 1.5 },
        velocity_mps: { x: paused ? 0 : 0.8, y: 0, z: 0 },
        localization_covariance_m2: 0.04,
        perception_age_ms: 45,
        minimum_clearance_m: obstacleInjected ? 0.52 : Number.parseFloat(mission.clearance),
        battery_percent: Math.max(35, 92 - currentProgress * 38),
        link_ok: true,
        geofence_ok: true,
        payload_mass_kg: currentProgress >= 0.42 && missionId === "coffee" ? pickupPayloadKg : 0,
        mission_progress: currentProgress,
        pickup_confirmed: currentProgress >= 0.42 && missionId === "coffee",
        local_replan_active: obstacleInjected && currentProgress < 0.7,
      }).then(setRuntimeSession).catch(() => {
        setRunning(false);
        setCompileError(copy.compileFailed);
      }).finally(() => {
        runtimeObservationPending.current = false;
      });
    }, 500);
    return () => window.clearInterval(interval);
  }, [copy.compileFailed, mission.clearance, missionId, obstacleInjected, paused, pickupPayloadKg, running, runtimeSessionId]);

  useEffect(() => {
    if (!complete || !runtimeSession || publicDemoConsole || runtimeTerminalSent.current) return;
    let cancelled = false;
    let retryTimer: number | undefined;
    const sendTerminalObservation = () => {
      if (cancelled || runtimeTerminalSent.current) return;
      if (runtimeObservationPending.current) {
        retryTimer = window.setTimeout(sendTerminalObservation, 50);
        return;
      }
      runtimeTerminalSent.current = true;
      runtimeObservationPending.current = true;
      const sequence = ++runtimeSequence.current;
      void apiClient.ingestAutonomyRuntimeObservation(runtimeSession.session_id, {
        sequence,
        monotonic_ms: Math.max(1, Math.round(performance.now())),
        armed: false,
        landed: true,
        position_m: { x: 0, y: 0, z: 0 },
        velocity_mps: { x: 0, y: 0, z: 0 },
        localization_covariance_m2: 0.04,
        perception_age_ms: 40,
        minimum_clearance_m: Number.parseFloat(mission.clearance),
        battery_percent: 54,
        link_ok: true,
        geofence_ok: true,
        payload_mass_kg: missionId === "coffee" ? pickupPayloadKg : 0,
        mission_progress: 1,
        pickup_confirmed: missionId === "coffee",
      }).then(setRuntimeSession).catch(() => setCompileError(copy.compileFailed)).finally(() => {
        runtimeObservationPending.current = false;
      });
    };
    sendTerminalObservation();
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [complete, copy.compileFailed, mission.clearance, missionId, pickupPayloadKg, runtimeSession]);

  useEffect(() => {
    if (!complete || evidenceReported.current || !onRunCompleted) return;
    if (!publicDemoConsole && !runtimeSession?.terminal) return;
    evidenceReported.current = true;
    const completedAt = new Date().toISOString();
    const sessionId = runtimeSession?.session_id
      ?? (previewRunId.current ??= `preview-run-${crypto.randomUUID()}`);
    onRunCompleted({
      schemaVersion: 1,
      id: sessionId,
      sessionId,
      contractId: qualification.contract.contract_id,
      completedAt,
      executionTarget: target,
      source: runtimeSession ? "backend" : "preview",
      evidenceChainHead: runtimeSession?.evidence_chain_head ?? "preview-only-no-signed-evidence-chain",
      observationCount: runtimeSession?.observation_count ?? 0,
      missionIntent: command,
      aircraftName: workspace?.aircraft.name ?? "Default preview aircraft",
      mapName: workspace?.mapPack.name ?? qualification.scene.name,
    });
  }, [command, complete, onRunCompleted, qualification.contract.contract_id, qualification.scene.name, runtimeSession, target, workspace?.aircraft.name, workspace?.mapPack.name]);

  useEffect(() => {
    compileGeneration.current += 1;
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
    runtimeRequestId.current = null;
    runtimeSequence.current = 0;
    runtimeTerminalSent.current = false;
    evidenceReported.current = false;
    previewRunId.current = null;
  }, [compileRequest]);

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
    const submittedRequest = compileRequest;
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
        result = await apiClient.compileAutonomyMission(submittedRequest);
        source = "backend";
      }
      if (
        generation !== compileGeneration.current
        || latestCompileRequest.current !== submittedRequest
      ) return;
      setCompileResult(result);
      setCompileSource(source);
      setPlanned(true);
      appendEvent(copy.events.planned);
    } catch {
      if (
        generation !== compileGeneration.current
        || latestCompileRequest.current !== submittedRequest
      ) return;
      setCompileResult(null);
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
      }
      if (!publicDemoConsole && !runtimeSession) {
        setLaunching(true);
        try {
          runtimeRequestId.current ??= crypto.randomUUID();
          const created = await apiClient.createAutonomyRuntimeSession(
            compileRequest,
            runtimeRequestId.current,
          );
          const sequence = ++runtimeSequence.current;
          const started = await apiClient.ingestAutonomyRuntimeObservation(
            created.session_id,
            {
              sequence,
              monotonic_ms: Math.max(1, Math.round(performance.now())),
              armed: true,
              landed: false,
              position_m: { x: 0, y: 0, z: 1.2 },
              velocity_mps: { x: 0, y: 0, z: 0.4 },
              localization_covariance_m2: 0.04,
              perception_age_ms: 40,
              minimum_clearance_m: Number.parseFloat(mission.clearance),
              battery_percent: 92,
              link_ok: true,
              geofence_ok: true,
              payload_mass_kg: 0,
              mission_progress: 0.02,
            },
          );
          setRuntimeSession(started);
        } catch {
          setCompileError(copy.compileFailed);
          return;
        } finally {
          setLaunching(false);
        }
      }
      setRunning(true);
      setPaused(false);
      appendEvent(copy.events.launched);
      return;
    }
    setPaused((current) => {
      appendEvent(current ? copy.events.launched : copy.events.paused);
      return !current;
    });
  };

  const resetMission = () => {
    if (runtimeSession && !runtimeSession.terminal && !publicDemoConsole) {
      void apiClient.stopAutonomyRuntimeSession(
        runtimeSession.session_id,
        "abort",
        "Operator reset the mission workspace.",
      );
    }
    setRunning(false);
    setLaunching(false);
    setPaused(false);
    setComplete(false);
    setProgress(0);
    setObstacleInjected(false);
    setRuntimeSession(null);
    runtimeRequestId.current = null;
    runtimeSequence.current = 0;
    runtimeTerminalSent.current = false;
    evidenceReported.current = false;
    previewRunId.current = null;
    setEvents([{ time: eventTime(), text: planned ? copy.events.planned : copy.events.ready }]);
  };

  const injectObstacle = () => {
    if (!planned || obstacleInjected || complete) return;
    setObstacleInjected(true);
    appendEvent(copy.events.obstacle);
  };

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
            <Link className="btn autonomy-edit-in-chat" to="/assistant">
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
              <dd>{qualification.execution_policy.adapter.replaceAll("_", " ")}</dd>
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

          <button className="btn btn-primary autonomy-plan-button" type="button" onClick={() => void planTrajectory()} disabled={planning || command.trim().length < 3}>
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
            <svg viewBox="0 0 900 520" role="img" aria-label={`${mission.name}: ${mission.objective}`}>
              <defs>
                <pattern id="autonomy-grid" width="32" height="32" patternUnits="userSpaceOnUse">
                  <path d="M 32 0 L 0 0 0 32" fill="none" stroke="currentColor" strokeWidth="0.7" />
                </pattern>
                <linearGradient id="autonomy-route-gradient" x1="0" x2="1">
                  <stop offset="0" stopColor="#24cfe5" />
                  <stop offset="0.52" stopColor="#7565f3" />
                  <stop offset="1" stopColor="#d545c6" />
                </linearGradient>
                <filter id="autonomy-glow"><feGaussianBlur stdDeviation="4" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
              </defs>
              <rect className="autonomy-grid" width="900" height="520" fill="url(#autonomy-grid)" />
              <g className={`autonomy-map-known ${perception === "vision" ? "is-vision" : ""}`}>
                <rect x="28" y="30" width="844" height="456" rx="24" className="autonomy-world-boundary" />
                {missionId === "coffee" ? (
                  <>
                    <g className="autonomy-floor-stack">
                      <path d="M64 365 250 365 310 315 125 315Z" />
                      <path d="M82 295 268 295 328 245 143 245Z" />
                      <path d="M100 225 286 225 346 175 161 175Z" />
                      <text x="118" y="205">FLOOR 3 · OFFICE</text>
                      <text x="98" y="278">FLOOR 2</text>
                      <text x="78" y="348">FLOOR 1 · LOBBY</text>
                    </g>
                    <rect x="150" y="70" width="120" height="92" rx="8" className="autonomy-obstacle" />
                    <rect x="385" y="330" width="180" height="110" rx="8" className="autonomy-obstacle" />
                    <rect x="615" y="52" width="220" height="78" rx="8" className="autonomy-obstacle" />
                    <g className="autonomy-stairs">
                      <path d="M286 354h78v-18h-62v-18h46v-18h-30v-18h16" />
                      <text x="275" y="380">NARROW STAIR CORE</text>
                    </g>
                    <g className="autonomy-tree" transform="translate(520 192)"><rect x="-4" y="13" width="8" height="30" /><circle cy="0" r="24" /><circle cx="-17" cy="8" r="15" /><circle cx="17" cy="8" r="15" /></g>
                    <g className="autonomy-tree" transform="translate(700 304)"><rect x="-4" y="13" width="8" height="30" /><circle cy="0" r="24" /><circle cx="-17" cy="8" r="15" /><circle cx="17" cy="8" r="15" /></g>
                    <g className="autonomy-sign" transform="translate(615 342)"><line y1="0" y2="48" /><rect x="-22" y="-18" width="44" height="26" rx="3" /><text y="0">SIGN</text></g>
                    <g className="autonomy-pole" transform="translate(750 218)"><line y1="-32" y2="34" /><circle cy="-34" r="6" /></g>
                    <text className="autonomy-zone-label" x="570" y="458">OUTDOOR COURTYARD · LIVE OBSTACLES</text>
                    <g className="autonomy-destination"><rect x="778" y="130" width="58" height="50" rx="10" /><Coffee x="795" y="142" width="24" height="24" /></g>
                  </>
                ) : missionId === "gates" ? (
                  <>
                    {[250, 455, 665].map((x, index) => <g className="autonomy-gate" key={x}><ellipse cx={x} cy={[300, 275, 238][index]} rx="16" ry="56" /><line x1={x} y1={[244, 219, 182][index]} x2={x} y2={[356, 331, 294][index]} /></g>)}
                    <rect x="365" y="72" width="90" height="110" rx="8" className="autonomy-obstacle" />
                    <rect x="545" y="350" width="116" height="106" rx="8" className="autonomy-obstacle" />
                  </>
                ) : (
                  <>
                    <rect x="136" y="55" width="136" height="270" rx="8" className="autonomy-obstacle" />
                    <rect x="314" y="370" width="182" height="86" rx="8" className="autonomy-obstacle" />
                    <rect x="508" y="55" width="122" height="140" rx="8" className="autonomy-obstacle" />
                    <rect x="678" y="260" width="144" height="194" rx="8" className="autonomy-obstacle" />
                  </>
                )}
              </g>
              {obstacleInjected ? <g className="autonomy-surprise-obstacle"><circle cx={missionId === "coffee" ? 520 : 505} cy={missionId === "coffee" ? 335 : 320} r="36" /><circle cx={missionId === "coffee" ? 520 : 505} cy={missionId === "coffee" ? 335 : 320} r="49" /></g> : null}
              <path className={`autonomy-route-shadow ${planned ? "is-visible" : ""}`} d={pathData(activePoints)} />
              <path className={`autonomy-route ${planned ? "is-visible" : ""}`} d={pathData(activePoints)} pathLength="1" />
              <g className="autonomy-map-marker autonomy-map-start" transform={`translate(${activePoints[0][0]} ${activePoints[0][1]})`}><circle r="15" /><text y="5">S</text></g>
              <g className="autonomy-map-marker autonomy-map-goal" transform={`translate(${activePoints[Math.floor(activePoints.length / 2)][0]} ${activePoints[Math.floor(activePoints.length / 2)][1]})`}><circle r="15" /><text y="5">{missionId === "coffee" ? "P" : "G"}</text></g>
              {planned ? (
                <g className="autonomy-drone" transform={`translate(${droneX} ${droneY})`} filter="url(#autonomy-glow)">
                  <circle r="23" />
                  <path d="M-16-16 16 16M16-16-16 16M-21-21h10M11-21h10M-21 21h10M11 21h10" />
                  <circle r="6" />
                </g>
              ) : null}
              {perception !== "map" && planned ? <path className="autonomy-camera-cone" d={`M ${droneX} ${droneY} L ${droneX + 115} ${droneY - 65} L ${droneX + 115} ${droneY + 65} Z`} /> : null}
            </svg>

            <div className="autonomy-camera-card">
              <div><Camera aria-hidden="true" /><span>{copy.cameraFeed}</span><i /></div>
              <div className="autonomy-camera-scene">
                <span className="autonomy-camera-horizon" />
                <span className="autonomy-camera-box"><small>{perception === "map" ? "MAP" : "FREE SPACE"}</small></span>
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
            <button className="btn btn-primary" type="button" disabled={launching || !planned || complete || !qualification.execution_policy.can_execute} onClick={() => void toggleFlight()}>
              {!qualification.execution_policy.can_execute ? <LockKeyhole aria-hidden="true" /> : running && !paused ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
              {running ? paused ? copy.resume : copy.pause : copy.run}
            </button>
            <button className="btn" type="button" onClick={resetMission}><RefreshCcw aria-hidden="true" />{copy.reset}</button>
            <button className="btn autonomy-inject-button" type="button" disabled={!planned || obstacleInjected || complete} onClick={injectObstacle}>
              <Sparkles aria-hidden="true" />{copy.inject}
            </button>
            <div className="autonomy-progress"><span><i style={{ width: `${Math.round(progress * 100)}%` }} /></span><strong>{Math.round(progress * 100)}%</strong></div>
          </div>
        </section>

        <aside className="autonomy-panel autonomy-brain-panel">
          <div className="autonomy-panel-heading">
            <div><BrainCircuit aria-hidden="true" /><span>{copy.brain}</span></div>
            <span className="autonomy-brain-rate">20 Hz safety loop</span>
          </div>
          <ol className="autonomy-brain-stages">
            {copy.brainStages.map((stage, index) => (
              <li key={stage} className={index === activeStage ? "is-active" : index < activeStage || complete ? "is-complete" : ""}>
                <span>{index < activeStage || complete ? <Check aria-hidden="true" /> : index + 1}</span>
                <div><strong>{stage}</strong><small>{index === 0 ? copy.modes[perception] : index === 4 && obstacleInjected ? copy.replanning : "ONLINE"}</small></div>
              </li>
            ))}
          </ol>

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
                  <strong>{runtimeComponentLabel(component.id, chinese)}</strong>
                  <small>{component.rate_hz ? `${component.rate_hz} Hz` : "—"}</small>
                </li>
              ))}
            </ul>
            <code className="autonomy-runtime-receipt">
              {runtimeSession
                ? `${runtimeSession.phase.toUpperCase()} · ${runtimeSession.session_id.slice(0, 18)} · ${runtimeSession.evidence_chain_head.slice(0, 12)}`
                : copy.runtimeAwaiting}
            </code>
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

          <div className={`autonomy-safety-gate ${qualification.execution_policy.can_execute ? "is-ready" : "is-denied"}`}>
            <h2>{qualification.execution_policy.can_execute ? <BadgeCheck aria-hidden="true" /> : <LockKeyhole aria-hidden="true" />}{copy.safetyGate}</h2>
            <div className="autonomy-safety-readout">
              <span>{copy.signedPacks}</span><strong>{qualification.execution_policy.validated_signed_pack_count}</strong>
            </div>
            {qualification.execution_policy.blockers.length ? (
              <ul>{qualification.execution_policy.blockers.slice(0, 4).map((blocker) => <li key={blocker}>{blocker.replaceAll(".", " · ")}</li>)}</ul>
            ) : <p>{copy.noBlockers}</p>}
          </div>

          <div className="autonomy-event-log">
            <h2>{copy.eventLog}</h2>
            <ul aria-live="polite">
              {events.map((event, index) => <li key={`${event.time}-${index}`}><time>{event.time}</time><span>{event.text}</span></li>)}
            </ul>
          </div>
        </aside>
      </section>
    </div>
  );
}
