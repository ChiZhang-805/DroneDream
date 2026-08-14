import {
  BrainCircuit,
  Camera,
  Check,
  CircleDotDashed,
  Coffee,
  Map,
  Navigation2,
  Pause,
  Play,
  Radar,
  RefreshCcw,
  Route,
  ShieldCheck,
  Sparkles,
  Waypoints,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import type { InterfaceLocale } from "../i18n/I18nProvider";

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
  kicker: "SIM · MISSION AUTONOMY",
  title: "Autonomy Lab",
  subtitle: "Give the aircraft a destination, a camera or a map. It builds a flyable trajectory, follows it smoothly, and replans when the world changes.",
  simulationOnly: "INTERACTIVE SIMULATION",
  independent: "Independent of parameter tuning",
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
  kicker: "SIM · 任务级自主飞行",
  title: "自主飞行",
  subtitle: "只给无人机终点、摄像头画面或一张地图，由它生成可飞航迹、平稳执行，并在环境变化时实时重规划。",
  simulationOnly: "交互式仿真",
  independent: "独立于控制参数调优",
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

export function AutonomyLab() {
  const { interfaceLocale } = useI18n();
  const copy = COPY_BY_LOCALE[interfaceLocale] ?? EN_COPY;
  const [missionId, setMissionId] = useState<MissionId>("coffee");
  const [perception, setPerception] = useState<PerceptionMode>("fusion");
  const [planned, setPlanned] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [complete, setComplete] = useState(false);
  const [progress, setProgress] = useState(0);
  const [obstacleInjected, setObstacleInjected] = useState(false);
  const [events, setEvents] = useState(() => [{ time: eventTime(), text: copy.events.ready }]);

  const missions = useMemo(() => Object.values(BASE_MISSIONS).map((base) => ({
    ...base,
    ...copy.missions[base.id],
  })), [copy]);
  const mission = missions.find(({ id }) => id === missionId) ?? missions[0];
  const activePoints = obstacleInjected ? mission.replanPoints : mission.points;
  const [droneX, droneY] = interpolatePath(activePoints, progress);
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

  const appendEvent = (text: string) => {
    setEvents((current) => [{ time: eventTime(), text }, ...current].slice(0, 4));
  };

  const chooseMission = (id: MissionId) => {
    setMissionId(id);
    setPlanned(false);
    setPlanning(false);
    setRunning(false);
    setPaused(false);
    setComplete(false);
    setProgress(0);
    setObstacleInjected(false);
    setEvents([{ time: eventTime(), text: copy.events.ready }]);
  };

  const planTrajectory = () => {
    setPlanning(true);
    setRunning(false);
    setPaused(false);
    setComplete(false);
    setProgress(0);
    window.setTimeout(() => {
      setPlanning(false);
      setPlanned(true);
      appendEvent(copy.events.planned);
    }, 520);
  };

  const toggleFlight = () => {
    if (!planned || complete) return;
    if (!running) {
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
    setRunning(false);
    setPaused(false);
    setComplete(false);
    setProgress(0);
    setObstacleInjected(false);
    setEvents([{ time: eventTime(), text: planned ? copy.events.planned : copy.events.ready }]);
  };

  const injectObstacle = () => {
    if (!planned || obstacleInjected || complete) return;
    setObstacleInjected(true);
    appendEvent(copy.events.obstacle);
  };

  return (
    <div className="autonomy-lab-page">
      <header className="autonomy-hero">
        <div>
          <span className="autonomy-kicker">{copy.kicker}</span>
          <div className="autonomy-title-line">
            <h1>{copy.title}</h1>
            <span><Sparkles aria-hidden="true" />{copy.simulationOnly}</span>
            <span className="autonomy-independent">{copy.independent}</span>
          </div>
          <p>{copy.subtitle}</p>
        </div>
        <div className={`autonomy-flight-status ${complete ? "is-complete" : running ? "is-running" : ""}`}>
          <span />
          {complete ? copy.completed : running ? copy.running : planned ? copy.planned : copy.ready}
        </div>
      </header>

      <section className="autonomy-workspace">
        <aside className="autonomy-panel autonomy-config-panel">
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
            <p>{copy.perceptionHelp}</p>
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
            <small className="autonomy-mode-description">{copy.modeDescriptions[perception]}</small>
          </div>

          <div className="autonomy-config-section autonomy-checkpoints">
            <h2><Waypoints aria-hidden="true" />{copy.taskFlow}</h2>
            <ol>
              <li><span>S</span><strong>{copy.start}</strong></li>
              <li><span>1</span><strong>{missionId === "coffee" ? copy.destination : copy.via}</strong></li>
              <li><span>G</span><strong>{missionId === "coffee" ? copy.returnHome : copy.destination}</strong></li>
            </ol>
          </div>

          <button className="btn btn-primary autonomy-plan-button" type="button" onClick={planTrajectory} disabled={planning}>
            {planning ? <RefreshCcw className="is-spinning" aria-hidden="true" /> : <Route aria-hidden="true" />}
            {planning ? copy.planning : planned ? copy.replan : copy.plan}
          </button>
        </aside>

        <section className="autonomy-panel autonomy-map-panel">
          <div className="autonomy-panel-heading autonomy-map-heading">
            <div><Map aria-hidden="true" /><span>{copy.environment}</span></div>
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
                    <rect x="150" y="70" width="120" height="235" rx="8" className="autonomy-obstacle" />
                    <rect x="385" y="330" width="180" height="110" rx="8" className="autonomy-obstacle" />
                    <rect x="615" y="52" width="220" height="78" rx="8" className="autonomy-obstacle" />
                    <g className="autonomy-stairs"><path d="M285 350h80v-18h-64v-18h48v-18h-32v-18h16" /></g>
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
            <button className="btn btn-primary" type="button" disabled={!planned || complete} onClick={toggleFlight}>
              {running && !paused ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
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
          <p className="autonomy-brain-copy">{copy.brainSubtitle}</p>
          <ol className="autonomy-brain-stages">
            {copy.brainStages.map((stage, index) => (
              <li key={stage} className={index === activeStage ? "is-active" : index < activeStage || complete ? "is-complete" : ""}>
                <span>{index < activeStage || complete ? <Check aria-hidden="true" /> : index + 1}</span>
                <div><strong>{stage}</strong><small>{index === 0 ? copy.modes[perception] : index === 4 && obstacleInjected ? copy.replanning : "ONLINE"}</small></div>
              </li>
            ))}
          </ol>

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
