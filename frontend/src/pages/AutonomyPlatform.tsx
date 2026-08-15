import {
  Activity,
  Airplay,
  Box,
  Camera,
  Check,
  ChevronRight,
  CircleCheck,
  Cpu,
  Database,
  FileClock,
  Gauge,
  HardDrive,
  Layers3,
  Map,
  MapPin,
  Navigation2,
  Orbit,
  Radar,
  Radio,
  Route,
  Save,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Upload,
  Video,
  Waypoints,
  Weight,
  Wrench,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Link,
  NavLink,
  Outlet,
  useOutletContext,
} from "react-router-dom";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import {
  loadAutonomyWorkspace,
  saveAutonomyWorkspace,
  type AutonomyAircraftProfile,
  type AutonomyMapPack,
  type AutonomyMapSourceFile,
  type AutonomySensorKind,
  type AutonomyWorkspaceState,
} from "../features/autonomy/workspaceStore";
import { useOptionalAuth } from "../features/auth/AuthContext";
import { consumeAutonomyHandoff } from "../features/experiment/assistantTaskRouter";
import { useI18n } from "../i18n/I18nProvider";
import { useEditionTheme } from "../theme/EditionThemeProvider";
import { AutonomyLab } from "./AutonomyLab";

type WorkspaceContext = {
  edition: BrandEditionId;
  chinese: boolean;
  workspace: AutonomyWorkspaceState;
  persist: (next: AutonomyWorkspaceState) => void;
};

type AutonomySectionId = "overview" | "aircraft" | "maps" | "mission" | "live" | "evidence";

const SECTION_ICONS = {
  overview: Orbit,
  aircraft: Navigation2,
  maps: Layers3,
  mission: Waypoints,
  live: Airplay,
  evidence: FileClock,
} as const;

const SECTION_COPY = {
  en: {
    overview: "Overview",
    aircraft: "Aircraft",
    maps: "Maps",
    mission: "Mission",
    live: "Live",
    evidence: "Evidence",
    tuningChat: "Tuning Chat",
    title: "Autonomy",
    draft: "Workspace draft",
  },
  zh: {
    overview: "总览",
    aircraft: "无人机",
    maps: "地图",
    mission: "任务",
    live: "实时运行",
    evidence: "证据回放",
    tuningChat: "Tuning Chat",
    title: "自主任务",
    draft: "工作区草稿",
  },
} as const;

function useAutonomyWorkspace(): WorkspaceContext {
  return useOutletContext<WorkspaceContext>();
}

function updatedWorkspace(
  workspace: AutonomyWorkspaceState,
  patch: Partial<AutonomyWorkspaceState>,
): AutonomyWorkspaceState {
  return { ...workspace, ...patch };
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="autonomy-asset-metric"><span>{icon}{label}</span><strong>{value}</strong></div>;
}

export function AutonomyPlatform() {
  const auth = useOptionalAuth();
  const theme = useEditionTheme();
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN" || interfaceLocale === "zh-TW";
  const copy = chinese ? SECTION_COPY.zh : SECTION_COPY.en;
  const ownerId = auth?.account?.id ?? "local";
  const edition = theme.id;
  const [workspace, setWorkspace] = useState(() => loadAutonomyWorkspace(ownerId, edition));

  useEffect(() => {
    setWorkspace(loadAutonomyWorkspace(ownerId, edition));
  }, [edition, ownerId]);

  const persist = useCallback((next: AutonomyWorkspaceState) => {
    setWorkspace(saveAutonomyWorkspace(ownerId, edition, next));
  }, [edition, ownerId]);

  const sections: Array<{ id: AutonomySectionId; to: string }> = [
    { id: "overview", to: "/autonomy/" },
    { id: "aircraft", to: "/autonomy/aircraft" },
    { id: "maps", to: "/autonomy/maps" },
    { id: "mission", to: "/autonomy/mission" },
    { id: "live", to: "/autonomy/live" },
    { id: "evidence", to: "/autonomy/evidence" },
  ];

  return (
    <div className="autonomy-platform-page">
      <header className="autonomy-platform-header">
        <div>
          <span>{edition.toUpperCase()} · AUTONOMY</span>
          <h1>{copy.title}</h1>
        </div>
        <div className="autonomy-platform-actions">
          <small><i />{copy.draft}</small>
          <Link className="btn" to="/assistant"><Sparkles aria-hidden="true" />{copy.tuningChat}</Link>
        </div>
      </header>

      <nav className="autonomy-section-switch" aria-label={copy.title}>
        {sections.map(({ id, to }) => {
          const Icon = SECTION_ICONS[id];
          return (
            <NavLink key={id} to={to} end={id === "overview"}>
              <Icon aria-hidden="true" />
              <span>{copy[id]}</span>
            </NavLink>
          );
        })}
      </nav>

      <main className="autonomy-platform-content">
        <Outlet context={{ edition, chinese, workspace, persist } satisfies WorkspaceContext} />
      </main>
    </div>
  );
}

export function AutonomyOverview() {
  const { chinese, workspace, edition } = useAutonomyWorkspace();
  const aircraft = workspace.aircraft;
  const mapPack = workspace.mapPack;
  const payloadKg = Math.max(0, aircraft.maximumTakeoffMassKg - aircraft.dryMassKg);
  const mapReady = mapPack.sourceFiles.length > 0 && mapPack.calibrated;
  const liveState = edition === "sim"
    ? (chinese ? "仿真可用" : "Simulation ready")
    : edition === "lab"
      ? (chinese ? "HITL 影子模式" : "HITL shadow")
      : (chinese ? "真机保持锁定" : "Aircraft locked");
  const cards = [
    {
      id: "aircraft",
      icon: Navigation2,
      title: chinese ? "当前无人机" : "Current aircraft",
      value: aircraft.name,
      meta: `${aircraft.dryMassKg.toFixed(2)} kg · ${payloadKg.toFixed(2)} kg ${chinese ? "载荷余量" : "payload margin"}`,
      state: `${aircraft.sensors.length} ${chinese ? "个传感器" : "sensors"}`,
      to: "/autonomy/aircraft",
    },
    {
      id: "maps",
      icon: Layers3,
      title: chinese ? "当前地图" : "Current map",
      value: mapPack.name,
      meta: `${mapPack.representation} · ${mapPack.resolutionM.toFixed(3)} m`,
      state: mapReady ? (chinese ? "已校准" : "Calibrated") : (chinese ? "需要配置" : "Configuration required"),
      to: "/autonomy/maps",
    },
    {
      id: "mission",
      icon: Waypoints,
      title: chinese ? "任务草稿" : "Mission draft",
      value: workspace.mission.intent,
      meta: `${chinese ? "阶段" : "Stage"} ${workspace.mission.currentStep + 1}/6`,
      state: chinese ? "来自 Tuning Chat" : "From Tuning Chat",
      to: "/autonomy/mission",
    },
    {
      id: "live",
      icon: Activity,
      title: chinese ? "执行状态" : "Execution state",
      value: liveState,
      meta: chinese ? "无活动运行会话" : "No active runtime session",
      state: edition.toUpperCase(),
      to: "/autonomy/live",
    },
  ];
  return (
    <section className="autonomy-overview-page">
      <div className="autonomy-overview-grid">
        {cards.map(({ id, icon: Icon, title, value, meta, state, to }) => (
          <Link className={`autonomy-overview-card is-${id}`} to={to} key={id}>
            <header><Icon aria-hidden="true" /><span>{title}</span><em>{state}</em></header>
            <strong>{value}</strong>
            <small>{meta}</small>
            <ChevronRight aria-hidden="true" />
          </Link>
        ))}
      </div>
      <div className="autonomy-readiness-strip">
        <Metric icon={<Weight aria-hidden="true" />} label={chinese ? "最大起飞重量" : "MTOM"} value={`${aircraft.maximumTakeoffMassKg.toFixed(2)} kg`} />
        <Metric icon={<ScanLine aria-hidden="true" />} label={chinese ? "机体包络" : "Body envelope"} value={`${aircraft.bodyLengthM.toFixed(2)} × ${aircraft.bodyWidthM.toFixed(2)} m`} />
        <Metric icon={<MapPin aria-hidden="true" />} label={chinese ? "地图资产" : "Map assets"} value={String(mapPack.sourceFiles.length)} />
        <Metric icon={<ShieldCheck aria-hidden="true" />} label={chinese ? "地图资格" : "Map qualification"} value={mapReady ? "READY" : "BLOCKED"} />
      </div>
    </section>
  );
}

const SENSOR_LABELS: Record<AutonomySensorKind, string> = {
  rgb: "RGB",
  depth: "Depth",
  stereo: "Stereo",
  thermal: "Thermal",
  lidar: "LiDAR",
  gps: "GNSS",
  vio: "VIO",
};

export function AutonomyAircraft() {
  const { chinese, workspace, persist, edition } = useAutonomyWorkspace();
  const [form, setForm] = useState(workspace.aircraft);
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(workspace.aircraft), [workspace.aircraft]);
  const payloadMargin = form.maximumTakeoffMassKg - form.dryMassKg;
  const thrustToWeight = form.maximumThrustN / (Math.max(form.maximumTakeoffMassKg, 0.01) * 9.80665);
  const valid = payloadMargin > 0 && thrustToWeight > 0;
  const numberField = (key: keyof AutonomyAircraftProfile, value: string) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return;
    setForm((current) => ({ ...current, [key]: numeric }));
    setSaved(false);
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    const next = { ...form, updatedAt: new Date().toISOString() };
    persist(updatedWorkspace(workspace, {
      aircraft: next,
      mission: { ...workspace.mission, aircraftProfileId: next.id, updatedAt: next.updatedAt },
    }));
    setSaved(true);
  };
  const toggleSensor = (sensor: AutonomySensorKind) => {
    setForm((current) => ({
      ...current,
      sensors: current.sensors.includes(sensor)
        ? current.sensors.filter((item) => item !== sensor)
        : [...current.sensors, sensor],
    }));
    setSaved(false);
  };
  return (
    <form className="autonomy-config-page" onSubmit={save}>
      <div className="autonomy-config-main">
        <section className="autonomy-config-card">
          <header><Navigation2 aria-hidden="true" /><h2>{chinese ? "机型身份" : "Aircraft identity"}</h2></header>
          <div className="autonomy-form-grid is-three">
            <label><span>{chinese ? "名称" : "Name"}</span><input value={form.name} maxLength={120} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label><span>{chinese ? "制造商" : "Manufacturer"}</span><input value={form.manufacturer} maxLength={120} onChange={(event) => setForm({ ...form, manufacturer: event.target.value })} /></label>
            <label><span>{chinese ? "机架" : "Airframe"}</span><input value={form.airframe} maxLength={120} onChange={(event) => setForm({ ...form, airframe: event.target.value })} /></label>
            <label className="is-wide"><span>{chinese ? "飞控固件" : "Flight controller firmware"}</span><input value={form.firmware} maxLength={120} onChange={(event) => setForm({ ...form, firmware: event.target.value })} /></label>
          </div>
        </section>

        <section className="autonomy-config-card">
          <header><Box aria-hidden="true" /><h2>{chinese ? "质量与包络" : "Mass & envelope"}</h2></header>
          <div className="autonomy-form-grid is-four">
            {([
              ["dryMassKg", chinese ? "空机重量 (kg)" : "Dry mass (kg)"],
              ["maximumTakeoffMassKg", chinese ? "最大起飞重量 (kg)" : "MTOM (kg)"],
              ["bodyLengthM", chinese ? "长度 (m)" : "Length (m)"],
              ["bodyWidthM", chinese ? "宽度 (m)" : "Width (m)"],
              ["bodyHeightM", chinese ? "高度 (m)" : "Height (m)"],
              ["rotorRadiusM", chinese ? "旋翼半径 (m)" : "Rotor radius (m)"],
              ["maximumThrustN", chinese ? "最大总推力 (N)" : "Maximum thrust (N)"],
              ["batteryEnergyWh", chinese ? "电池能量 (Wh)" : "Battery energy (Wh)"],
            ] as Array<[keyof AutonomyAircraftProfile, string]>).map(([key, label]) => (
              <label key={key}><span>{label}</span><input type="number" min="0" step="0.01" value={String(form[key])} onChange={(event) => numberField(key, event.target.value)} /></label>
            ))}
            <label><span>{chinese ? "返航保留电量 (%)" : "Reserve battery (%)"}</span><input type="number" min="0" max="95" step="1" value={form.reserveBatteryPercent} onChange={(event) => numberField("reserveBatteryPercent", event.target.value)} /></label>
          </div>
        </section>

        <section className="autonomy-config-card">
          <header><Radar aria-hidden="true" /><h2>{chinese ? "机载感知" : "Onboard perception"}</h2></header>
          <div className="autonomy-choice-grid">
            {(Object.keys(SENSOR_LABELS) as AutonomySensorKind[]).map((sensor) => (
              <button type="button" key={sensor} className={form.sensors.includes(sensor) ? "is-selected" : ""} onClick={() => toggleSensor(sensor)}>
                {sensor === "rgb" || sensor === "depth" || sensor === "stereo" || sensor === "thermal" ? <Camera aria-hidden="true" /> : sensor === "lidar" ? <Radio aria-hidden="true" /> : <Cpu aria-hidden="true" />}
                <span>{SENSOR_LABELS[sensor]}</span>
                {form.sensors.includes(sensor) ? <Check aria-hidden="true" /> : null}
              </button>
            ))}
          </div>
        </section>
      </div>

      <aside className="autonomy-config-summary">
        <header><Gauge aria-hidden="true" /><h2>{chinese ? "飞行包络" : "Flight envelope"}</h2></header>
        <Metric icon={<Weight aria-hidden="true" />} label={chinese ? "可用载荷" : "Payload margin"} value={`${payloadMargin.toFixed(2)} kg`} />
        <Metric icon={<Activity aria-hidden="true" />} label={chinese ? "满载推重比" : "Loaded thrust / weight"} value={thrustToWeight.toFixed(2)} />
        <Metric icon={<ScanLine aria-hidden="true" />} label={chinese ? "对角包络" : "Diagonal envelope"} value={`${Math.hypot(form.bodyLengthM, form.bodyWidthM).toFixed(2)} m`} />
        <Metric icon={<Camera aria-hidden="true" />} label={chinese ? "感知设备" : "Perception devices"} value={String(form.sensors.length)} />
        {!valid ? <p className="autonomy-config-error">{chinese ? "最大起飞重量必须大于空机重量。" : "MTOM must exceed dry mass."}</p> : null}
        <button className="btn btn-primary" type="submit" disabled={!valid}><Save aria-hidden="true" />{saved ? (chinese ? "已保存" : "Saved") : (chinese ? "保存机型" : "Save aircraft")}</button>
        {edition === "universal" ? <Link className="btn" to="/vehicle-studio"><Wrench aria-hidden="true" />Vehicle Studio</Link> : null}
        <small>{chinese ? "更新于" : "Updated"} {formatTime(workspace.aircraft.updatedAt)}</small>
      </aside>
    </form>
  );
}

const SEMANTIC_LABELS: Record<AutonomyMapPack["semanticLayers"][number], string> = {
  "free-space": "Free space",
  stairs: "Stairs",
  doors: "Doors",
  gates: "Gates",
  people: "People",
  "pickup-zones": "Pickup zones",
};

export function AutonomyMaps() {
  const { chinese, workspace, persist } = useAutonomyWorkspace();
  const [form, setForm] = useState(workspace.mapPack);
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(workspace.mapPack), [workspace.mapPack]);
  const ready = form.sourceFiles.length > 0 && form.calibrated;
  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const importedAt = new Date().toISOString();
    const incoming: AutonomyMapSourceFile[] = [...files].slice(0, 24).map((file) => ({
      name: file.name,
      bytes: file.size,
      format: file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "unknown",
      importedAt,
    }));
    setForm((current) => ({ ...current, sourceFiles: [...current.sourceFiles, ...incoming].slice(0, 24) }));
    setSaved(false);
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    const next = { ...form, updatedAt: new Date().toISOString() };
    persist(updatedWorkspace(workspace, {
      mapPack: next,
      mission: { ...workspace.mission, mapPackId: next.id, updatedAt: next.updatedAt },
    }));
    setSaved(true);
  };
  const toggleSemantic = (layer: AutonomyMapPack["semanticLayers"][number]) => {
    setForm((current) => ({
      ...current,
      semanticLayers: current.semanticLayers.includes(layer)
        ? current.semanticLayers.filter((item) => item !== layer)
        : [...current.semanticLayers, layer],
    }));
    setSaved(false);
  };
  return (
    <form className="autonomy-config-page autonomy-maps-page" onSubmit={save}>
      <div className="autonomy-config-main">
        <section className="autonomy-config-card">
          <header><Layers3 aria-hidden="true" /><h2>{chinese ? "Map Pack" : "Map Pack"}</h2><em className={ready ? "is-ready" : ""}>{ready ? "READY" : "UNQUALIFIED"}</em></header>
          <div className="autonomy-form-grid is-four">
            <label className="is-wide"><span>{chinese ? "地图名称" : "Map name"}</span><input value={form.name} maxLength={120} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label><span>{chinese ? "三维表示" : "3D representation"}</span><select value={form.representation} onChange={(event) => setForm({ ...form, representation: event.target.value as AutonomyMapPack["representation"] })}><option value="hybrid-3d">Hybrid 3D</option><option value="mesh">Mesh</option><option value="point-cloud">Point cloud</option><option value="occupancy">Occupancy / ESDF</option><option value="terrain">Terrain / DEM</option></select></label>
            <label><span>{chinese ? "坐标系" : "Coordinate frame"}</span><select value={form.coordinateFrame} onChange={(event) => setForm({ ...form, coordinateFrame: event.target.value as AutonomyMapPack["coordinateFrame"] })}><option>ENU</option><option>NED</option><option>WGS84</option><option value="building-local">Building local</option></select></label>
            <label><span>{chinese ? "分辨率 (m)" : "Resolution (m)"}</span><input type="number" min="0.005" step="0.005" value={form.resolutionM} onChange={(event) => setForm({ ...form, resolutionM: Number(event.target.value) })} /></label>
            <label><span>{chinese ? "楼层数" : "Floors"}</span><input type="number" min="1" max="500" step="1" value={form.floorCount} onChange={(event) => setForm({ ...form, floorCount: Number(event.target.value) })} /></label>
            <label><span>{chinese ? "实时更新" : "Live updates"}</span><select value={form.liveUpdates} onChange={(event) => setForm({ ...form, liveUpdates: event.target.value as AutonomyMapPack["liveUpdates"] })}><option value="vision-slam">Vision SLAM</option><option value="depth-fusion">Depth fusion</option><option value="lidar-fusion">LiDAR fusion</option><option value="fixed">Fixed map</option></select></label>
            <label className="autonomy-check-control"><input type="checkbox" checked={form.calibrated} onChange={(event) => setForm({ ...form, calibrated: event.target.checked })} /><span>{chinese ? "比例和坐标已校准" : "Scale and frame calibrated"}</span></label>
          </div>
        </section>

        <section className="autonomy-config-card">
          <header><Database aria-hidden="true" /><h2>{chinese ? "地图资产" : "Map assets"}</h2></header>
          <label className="autonomy-map-upload">
            <Upload aria-hidden="true" />
            <strong>{chinese ? "登记本地地图资产" : "Register local map assets"}</strong>
            <span>GLB · GLTF · PCD · PLY · LAS · LAZ · GeoTIFF · BT · YAML</span>
            <input type="file" multiple accept=".glb,.gltf,.pcd,.ply,.las,.laz,.tif,.tiff,.bt,.yaml,.yml,.pgm,.png,.json,.geojson" onChange={(event) => addFiles(event.target.files)} />
          </label>
          <div className="autonomy-map-assets">
            {form.sourceFiles.length ? form.sourceFiles.map((file, index) => (
              <div key={`${file.name}-${index}`}><HardDrive aria-hidden="true" /><span><strong>{file.name}</strong><small>{file.format.toUpperCase()} · {(file.bytes / 1_000_000).toFixed(2)} MB</small></span><button type="button" onClick={() => setForm({ ...form, sourceFiles: form.sourceFiles.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div>
            )) : <p className="autonomy-honest-empty">{chinese ? "尚未登记地图资产；系统不会用二维示意图冒充可规划地图。" : "No map assets registered. A diagram is never treated as a planning map."}</p>}
          </div>
        </section>

        <section className="autonomy-config-card">
          <header><MapPin aria-hidden="true" /><h2>{chinese ? "语义图层" : "Semantic layers"}</h2></header>
          <div className="autonomy-choice-grid is-semantic">
            {(Object.keys(SEMANTIC_LABELS) as AutonomyMapPack["semanticLayers"][number][]).map((layer) => (
              <button type="button" key={layer} className={form.semanticLayers.includes(layer) ? "is-selected" : ""} onClick={() => toggleSemantic(layer)}><MapPin aria-hidden="true" /><span>{SEMANTIC_LABELS[layer]}</span>{form.semanticLayers.includes(layer) ? <Check aria-hidden="true" /> : null}</button>
            ))}
          </div>
        </section>
      </div>
      <aside className="autonomy-config-summary">
        <header><Map aria-hidden="true" /><h2>{chinese ? "地图资格" : "Map qualification"}</h2></header>
        <Metric icon={<HardDrive aria-hidden="true" />} label={chinese ? "资产文件" : "Assets"} value={String(form.sourceFiles.length)} />
        <Metric icon={<ScanLine aria-hidden="true" />} label={chinese ? "分辨率" : "Resolution"} value={`${form.resolutionM.toFixed(3)} m`} />
        <Metric icon={<Layers3 aria-hidden="true" />} label={chinese ? "语义图层" : "Semantic layers"} value={String(form.semanticLayers.length)} />
        <Metric icon={<ShieldCheck aria-hidden="true" />} label={chinese ? "状态" : "Status"} value={ready ? "READY" : "BLOCKED"} />
        <button className="btn btn-primary" type="submit"><Save aria-hidden="true" />{saved ? (chinese ? "已保存" : "Saved") : (chinese ? "保存 Map Pack" : "Save Map Pack")}</button>
        <small>{chinese ? "更新于" : "Updated"} {formatTime(workspace.mapPack.updatedAt)}</small>
      </aside>
    </form>
  );
}

const MISSION_STEPS = [
  { id: "contract", icon: Waypoints, en: "Task contract", zh: "任务合同" },
  { id: "aircraft", icon: Navigation2, en: "Aircraft", zh: "无人机" },
  { id: "world", icon: Layers3, en: "World", zh: "环境" },
  { id: "trajectory", icon: Route, en: "Trajectory", zh: "航迹规划" },
  { id: "safety", icon: ShieldCheck, en: "Safety", zh: "安全策略" },
  { id: "review", icon: CircleCheck, en: "Review", zh: "检查验证" },
] as const;

export function AutonomyMission() {
  const { chinese, workspace, persist } = useAutonomyWorkspace();
  const step = workspace.mission.currentStep;
  const handoffConsumed = useRef(false);
  useEffect(() => {
    if (handoffConsumed.current) return;
    handoffConsumed.current = true;
    const handoff = consumeAutonomyHandoff();
    if (!handoff) return;
    const updatedAt = new Date().toISOString();
    persist(updatedWorkspace(workspace, { mission: { ...workspace.mission, intent: handoff, currentStep: 0, updatedAt } }));
  }, [persist, workspace]);
  const selectStep = (currentStep: number) => {
    const updatedAt = new Date().toISOString();
    persist(updatedWorkspace(workspace, { mission: { ...workspace.mission, currentStep, updatedAt } }));
  };
  const mapReady = workspace.mapPack.sourceFiles.length > 0 && workspace.mapPack.calibrated;
  const aircraftReady = workspace.aircraft.maximumTakeoffMassKg > workspace.aircraft.dryMassKg;
  const blockers = [
    ...(!aircraftReady ? [chinese ? "机型质量包络无效" : "Aircraft mass envelope is invalid"] : []),
    ...(!mapReady ? [chinese ? "Map Pack 尚未完成资产登记与校准" : "Map Pack requires assets and calibration"] : []),
  ];
  return (
    <section className="autonomy-mission-page">
      <ol className="autonomy-mission-stepper">
        {MISSION_STEPS.map((item, index) => {
          const Icon = item.icon;
          return <li key={item.id} className={index === step ? "is-active" : index < step ? "is-complete" : ""}><button type="button" onClick={() => selectStep(index)}><span>{index < step ? <Check aria-hidden="true" /> : index + 1}</span><Icon aria-hidden="true" /><strong>{chinese ? item.zh : item.en}</strong></button></li>;
        })}
      </ol>

      <div className="autonomy-mission-stage">
        {step === 0 ? <section><header><Waypoints aria-hidden="true" /><h2>{chinese ? "任务合同" : "Task contract"}</h2><Link className="btn" to="/assistant"><Sparkles aria-hidden="true" />Tuning Chat</Link></header><blockquote>{workspace.mission.intent}</blockquote><div className="autonomy-contract-points"><span><i>S</i>{chinese ? "起点" : "Start"}</span><ChevronRight /><span><i>1</i>{chinese ? "工作点" : "Work point"}</span><ChevronRight /><span><i>H</i>{chinese ? "返航" : "Return"}</span></div></section> : null}
        {step === 1 ? <section><header><Navigation2 aria-hidden="true" /><h2>{workspace.aircraft.name}</h2><Link className="btn" to="/autonomy/aircraft">{chinese ? "编辑机型" : "Edit aircraft"}</Link></header><div className="autonomy-stage-metrics"><Metric icon={<Weight />} label={chinese ? "空机重量" : "Dry mass"} value={`${workspace.aircraft.dryMassKg.toFixed(2)} kg`} /><Metric icon={<Gauge />} label="MTOM" value={`${workspace.aircraft.maximumTakeoffMassKg.toFixed(2)} kg`} /><Metric icon={<Camera />} label={chinese ? "感知设备" : "Sensors"} value={String(workspace.aircraft.sensors.length)} /><Metric icon={<Cpu />} label={chinese ? "飞控" : "Firmware"} value={workspace.aircraft.firmware} /></div></section> : null}
        {step === 2 ? <section><header><Layers3 aria-hidden="true" /><h2>{workspace.mapPack.name}</h2><Link className="btn" to="/autonomy/maps">{chinese ? "编辑地图" : "Edit map"}</Link></header><div className="autonomy-stage-metrics"><Metric icon={<Database />} label={chinese ? "表示" : "Representation"} value={workspace.mapPack.representation} /><Metric icon={<ScanLine />} label={chinese ? "分辨率" : "Resolution"} value={`${workspace.mapPack.resolutionM.toFixed(3)} m`} /><Metric icon={<HardDrive />} label={chinese ? "资产" : "Assets"} value={String(workspace.mapPack.sourceFiles.length)} /><Metric icon={<ShieldCheck />} label={chinese ? "资格" : "Qualification"} value={mapReady ? "READY" : "BLOCKED"} /></div></section> : null}
        {step === 3 ? <section><header><Route aria-hidden="true" /><h2>{chinese ? "航迹目标" : "Trajectory objectives"}</h2></header><div className="autonomy-planner-choices"><button className="is-selected"><ShieldCheck />{chinese ? "安全优先" : "Safety first"}</button><button><Activity />{chinese ? "平滑飞行" : "Smooth flight"}</button><button><Gauge />{chinese ? "时间效率" : "Time efficient"}</button><button><Cpu />{chinese ? "能量效率" : "Energy efficient"}</button></div></section> : null}
        {step === 4 ? <section><header><ShieldCheck aria-hidden="true" /><h2>{chinese ? "安全策略" : "Safety policy"}</h2></header><div className="autonomy-safety-policy-list"><span><Radio />{chinese ? "失联" : "Link loss"}<strong>HOLD → LAND</strong></span><span><MapPin />{chinese ? "越界" : "Geofence"}<strong>LAND</strong></span><span><Camera />{chinese ? "感知过期" : "Stale perception"}<strong>HOLD</strong></span><span><Weight />{chinese ? "载荷超限" : "Payload overrun"}<strong>LAND</strong></span></div></section> : null}
        {step === 5 ? <section><header><CircleCheck aria-hidden="true" /><h2>{chinese ? "检查并验证" : "Review & qualify"}</h2></header><div className="autonomy-review-block"><div className={aircraftReady ? "is-ready" : "is-blocked"}><Navigation2 /><span>{chinese ? "无人机" : "Aircraft"}</span><strong>{aircraftReady ? "READY" : "BLOCKED"}</strong></div><div className={mapReady ? "is-ready" : "is-blocked"}><Layers3 /><span>Map Pack</span><strong>{mapReady ? "READY" : "BLOCKED"}</strong></div><div className="is-ready"><ShieldCheck /><span>{chinese ? "安全策略" : "Safety policy"}</span><strong>BOUND</strong></div></div>{blockers.length ? <ul className="autonomy-review-blockers">{blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul> : <Link className="btn btn-primary" to="/autonomy/live"><Airplay />{chinese ? "进入仿真验证" : "Open simulation validation"}</Link>}</section> : null}
      </div>

      <footer className="autonomy-mission-footer">
        <button className="btn" type="button" disabled={step === 0} onClick={() => selectStep(step - 1)}>{chinese ? "上一步" : "Back"}</button>
        <span>{step + 1} / {MISSION_STEPS.length}</span>
        <button className="btn btn-primary" type="button" disabled={step === MISSION_STEPS.length - 1} onClick={() => selectStep(step + 1)}>{chinese ? "下一步" : "Next"}<ChevronRight aria-hidden="true" /></button>
      </footer>
    </section>
  );
}

export function AutonomyLive() {
  return <AutonomyLab embedded />;
}

export function AutonomyEvidence() {
  const { chinese, workspace } = useAutonomyWorkspace();
  const snapshots = [
    { icon: Navigation2, label: chinese ? "机型快照" : "Aircraft snapshot", value: workspace.aircraft.name, time: workspace.aircraft.updatedAt },
    { icon: Layers3, label: "Map Pack", value: workspace.mapPack.name, time: workspace.mapPack.updatedAt },
    { icon: Waypoints, label: chinese ? "任务合同" : "Mission contract", value: workspace.mission.id, time: workspace.mission.updatedAt },
  ];
  return (
    <section className="autonomy-evidence-page">
      <div className="autonomy-evidence-bindings">
        {snapshots.map(({ icon: Icon, label, value, time }) => <article key={label}><Icon aria-hidden="true" /><span><small>{label}</small><strong>{value}</strong></span><time>{formatTime(time)}</time></article>)}
      </div>
      <div className="autonomy-evidence-empty">
        <FileClock aria-hidden="true" />
        <h2>{chinese ? "尚无已完成的运行证据" : "No completed runtime evidence"}</h2>
        <div><span>Mission Contract</span><ChevronRight /><span>Observations</span><ChevronRight /><span>Decisions</span><ChevronRight /><span>Replay</span></div>
        <Link className="btn btn-primary" to="/autonomy/live"><Video aria-hidden="true" />{chinese ? "打开实时运行" : "Open Live Mission"}</Link>
      </div>
    </section>
  );
}
