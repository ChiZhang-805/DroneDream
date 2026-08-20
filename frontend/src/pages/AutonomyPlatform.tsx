import {
  Activity,
  Airplay,
  ArrowUp,
  Box,
  Camera,
  Check,
  ChevronRight,
  CircleCheck,
  CircleUserRound,
  Cpu,
  Database,
  FileClock,
  Gauge,
  HardDrive,
  Layers3,
  Map,
  MapPin,
  Mic,
  Navigation2,
  Orbit,
  Plus,
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
  type Dispatch,
  type FormEvent,
  type ReactNode,
  type SetStateAction,
} from "react";
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  useLocation,
  useOutletContext,
} from "react-router-dom";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { apiClient } from "../api/client";
import { openAppSettings } from "../appSettings";
import { AssistantModelPicker } from "../components/AssistantModelPicker";
import {
  AUTONOMY_AIRCRAFT_LIMITS,
  autonomyAircraftRadiusM,
  defaultAutonomyWorkspace,
  isAutonomyAircraftProfileValid,
  loadAutonomyWorkspace,
  saveAutonomyWorkspace,
  type AutonomyAircraftProfile,
  type AutonomyConversationMessage,
  type AutonomyEvidenceRecord,
  type AutonomyMapPack,
  type AutonomyMapSourceFile,
  type AutonomyMissionPlanSnapshot,
  type AutonomySensorKind,
  type AutonomyWorkspaceState,
} from "../features/autonomy/workspaceStore";
import {
  loadAutonomyAssetLibrary,
  saveAutonomyAssetLibrary,
  withCurrentAutonomyAssets,
  type AutonomyAssetLibrary,
} from "../features/autonomy/assetLibraryStore";
import {
  createLocalAutonomyPreview,
  type AutonomyMissionId,
} from "../features/autonomy/missionAutonomy";
import {
  autonomyAssetBlockerMessage,
  autonomyCanonicalSha256,
  autonomyHarnessRequest,
  autonomyModelContext,
  autonomyPlannerBindingIssues,
  localAutonomyHarnessInspection,
  parseAutonomyPlannerArtifact,
  type AutonomyPlannerArtifact,
} from "../features/autonomy/missionHarness";
import { useOptionalAuth } from "../features/auth/AuthContext";
import { publicDemoConsole } from "../features/demo/publicDemo";
import { consumeAutonomyHandoff } from "../features/experiment/assistantTaskRouter";
import { orchestrateAssistantTurn } from "../features/experiment/assistantOrchestration";
import { useVoiceInput } from "../features/experiment/useVoiceInput";
import {
  activeAssistantTenantContext,
  createExperimentWorkspaceId,
} from "../features/experiment/workspaceRegistry";
import {
  completeManagedModelCatalog,
  DEFAULT_MANAGED_MODEL_CATALOG,
  getManagedModelCatalog,
  managedModelAvailableForAssistant,
} from "../features/settings/cloudModelAccess";
import { useModelAccess } from "../features/settings/ModelAccessContext";
import { useI18n } from "../i18n/I18nProvider";
import { useEditionTheme } from "../theme/EditionThemeProvider";
import type {
  AutonomyBundledMapManifest,
  AutonomyCompileAssetContext,
  AutonomyCompileRequest,
  AutonomyCompileResponse,
  AutonomyHarnessInspectResponse,
  AutonomyMapPackQualificationRequest,
  AutonomyVehiclePackQualificationRequest,
} from "../types/api";
import { AutonomyLab } from "./AutonomyLab";

type WorkspaceContext = {
  edition: BrandEditionId;
  chinese: boolean;
  workspace: AutonomyWorkspaceState;
  assetLibrary: AutonomyAssetLibrary;
  persist: (next: AutonomyWorkspaceState) => void;
  selectAircraft: (aircraftId: string) => void;
  selectMap: (mapId: string) => void;
  missionComposerDraft: string;
  setMissionComposerDraft: Dispatch<SetStateAction<string>>;
};

type AutonomySectionId = "overview" | "aircraft" | "maps" | "live" | "evidence";

const SECTION_ICONS = {
  overview: Orbit,
  aircraft: Navigation2,
  maps: Layers3,
  live: Airplay,
  evidence: FileClock,
} as const;

const SECTION_COPY = {
  en: {
    overview: "Overview",
    aircraft: "Aircraft",
    maps: "Maps",
    live: "Live",
    evidence: "Evidence",
    title: "Autonomy",
  },
  zh: {
    overview: "总览",
    aircraft: "无人机",
    maps: "地图",
    live: "实时运行",
    evidence: "证据回放",
    title: "Autonomy",
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

function vehicleQualificationRequest(
  aircraft: AutonomyAircraftProfile,
): AutonomyVehiclePackQualificationRequest {
  return {
    pack_id: aircraft.id,
    version: aircraft.version,
    autopilot: aircraft.autopilot,
    firmware: aircraft.firmware,
    flight_controller: aircraft.flightController,
    control_interface: aircraft.controlInterface,
    dry_mass_kg: aircraft.dryMassKg,
    max_takeoff_mass_kg: aircraft.maximumTakeoffMassKg,
    max_total_thrust_n: aircraft.maximumThrustN,
    body_size_m: { x: aircraft.bodyLengthM, y: aircraft.bodyWidthM, z: aircraft.bodyHeightM },
    rotor_radius_m: aircraft.rotorRadiusM,
    center_of_gravity_m: aircraft.centerOfGravityM,
    inertia_kg_m2: aircraft.inertiaKgM2,
    battery_energy_wh: aircraft.batteryEnergyWh,
    reserve_battery_percent: aircraft.reserveBatteryPercent,
    maximum_pickup_payload_kg: aircraft.maximumPickupPayloadKg,
    maximum_speed_mps: aircraft.maximumSpeedMps,
    maximum_acceleration_mps2: aircraft.maximumAccelerationMps2,
    maximum_climb_mps: aircraft.maximumClimbMps,
    maximum_descent_mps: aircraft.maximumDescentMps,
    maximum_tilt_deg: aircraft.maximumTiltDeg,
    command_link_latency_ms: aircraft.commandLink.latencyMs,
    command_link_bandwidth_mbps: aircraft.commandLink.bandwidthMbps,
    sensors: aircraft.sensorMounts.map((sensor) => ({
      sensor_id: sensor.id,
      kind: sensor.kind,
      calibrated: sensor.calibrated,
      calibration_status: sensor.calibrationStatus,
      position_m: sensor.positionM,
      roll_pitch_yaw_deg: sensor.rollPitchYawDeg,
      rate_hz: sensor.rateHz,
      calibration_age_days: sensor.calibrationAgeDays,
    })),
  };
}

function mapQualificationRequest(mapPack: AutonomyMapPack): AutonomyMapPackQualificationRequest {
  return {
    schema_version: "dronedream.autonomy.map-pack-qualification.v1",
    name: mapPack.name,
    pack_id: mapPack.id,
    version: mapPack.version,
    compiler_scene_id: mapPack.compilerSceneId ?? "",
    representation: mapPack.representation,
    coordinate_frame: mapPack.coordinateFrame,
    resolution_m: mapPack.resolutionM,
    floor_count: mapPack.floorCount,
    bounds_m: mapPack.boundsM,
    origin: {
      latitude: mapPack.origin.latitude,
      longitude: mapPack.origin.longitude,
      altitude_m: mapPack.origin.altitudeM,
    },
    live_updates: mapPack.liveUpdates,
    calibrated: mapPack.calibrated,
    confidence_percent: mapPack.confidencePercent,
    semantic_layers: mapPack.semanticLayers,
    planning_layers: mapPack.planningLayers,
    source_asset_receipt_ids: mapPack.sourceFiles
      .map((file) => file.receiptId)
      .filter((receiptId): receiptId is string => Boolean(receiptId)),
  };
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

function normalizedAutonomyPath(pathname: string): string {
  const withoutBasename = pathname === "/console"
    ? "/"
    : pathname.startsWith("/console/")
      ? pathname.slice("/console".length)
      : pathname;
  return withoutBasename.replace(/\/+$/u, "") || "/";
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="autonomy-asset-metric"><span>{icon}{label}</span><strong>{value}</strong></div>;
}

function AutonomyTemplateIcon({ index }: { index: number }) {
  const Icon = [Route, Camera, Layers3][index] ?? Route;
  return <Icon className="assistant-example-icon" aria-hidden="true" strokeWidth={1.8} />;
}

function AutonomyCloudTerminalIcon() {
  return (
    <svg
      className="assistant-cloud-terminal-icon"
      viewBox="0 0 112 80"
      role="presentation"
      focusable="false"
    >
      <path
        d="M34 65h48c14.4 0 26-10.8 26-24.2 0-12.5-10.2-22.9-23.3-24.1C79.2 7.3 68.5 2 57.2 4.2 43.8 6.8 34.4 17 32.9 29.4 17.7 29.9 5.5 40.2 5.5 47.8 5.5 57.4 18.3 65 34 65Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        className="assistant-terminal-chevron"
        d="m38 39 10 8-10 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        className="assistant-terminal-underscore"
        d="M55 55h17"
        fill="none"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function missionIdForScene(sceneId: string, intent = ""): AutonomyMissionId {
  if (sceneId === "forest-gate-inspection") return "gates";
  if (sceneId === "service-corridor-dock") return "narrow";
  const normalized = intent.toLocaleLowerCase();
  if (/gate|圆门|圆环|穿门/u.test(normalized)) return "gates";
  if (/narrow|dock|走廊|corridor|停靠|狭窄|楼梯/u.test(normalized)) return "narrow";
  return "coffee";
}

function inferredSceneId(intent: string, mapPack: AutonomyMapPack): string {
  if (mapPack.compilerSceneId) return mapPack.compilerSceneId;
  void intent;
  return "school-campus-v1";
}

function compileRequestForWorkspace(
  edition: BrandEditionId,
  workspace: AutonomyWorkspaceState,
  intent: string,
  assetContext: AutonomyCompileAssetContext,
): AutonomyCompileRequest {
  const visualSensors = workspace.aircraft.sensors.some((sensor) => (
    sensor === "rgb"
    || sensor === "depth"
    || sensor === "stereo"
    || sensor === "thermal"
    || sensor === "vio"
  ));
  const mapReady = autonomyMapPackQualified(workspace.mapPack);
  return {
    edition,
    execution_target: "simulation",
    natural_language: intent,
    scene_id: inferredSceneId(intent, workspace.mapPack),
    perception_mode: visualSensors && mapReady ? "fusion" : visualSensors ? "vision" : "map",
    vehicle: {
      dry_mass_kg: workspace.aircraft.dryMassKg,
      launch_payload_kg: 0,
      pickup_payload_kg: workspace.aircraft.maximumPickupPayloadKg,
      max_takeoff_mass_kg: workspace.aircraft.maximumTakeoffMassKg,
      max_total_thrust_n: workspace.aircraft.maximumThrustN,
      radius_m: autonomyAircraftRadiusM(workspace.aircraft),
      max_speed_mps: workspace.aircraft.maximumSpeedMps,
      max_acceleration_mps2: workspace.aircraft.maximumAccelerationMps2,
      reserve_battery_percent: workspace.aircraft.reserveBatteryPercent,
    },
    evidence: {
      simulation_qualified: false,
      signed_vehicle_pack_id: null,
      operator_confirmed: false,
      localization_ready: false,
      link_ready: false,
      geofence_ready: false,
      battery_ready: false,
    },
    asset_context: assetContext,
  };
}

function normalizedAssetReference(value: string): string {
  return value.normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

function resolveMissionAssets(
  workspace: AutonomyWorkspaceState,
  assetLibrary: AutonomyAssetLibrary,
  naturalLanguage: string,
): AutonomyWorkspaceState {
  const normalizedIntent = normalizedAssetReference(naturalLanguage);
  const referencedAsset = <T extends { id: string; name: string }>(assets: T[]): T | null => assets
    .map((asset) => ({
      asset,
      references: [asset.name, asset.id]
        .map(normalizedAssetReference)
        .filter((reference) => reference.length >= 4),
    }))
    .filter(({ references }) => references.some((reference) => normalizedIntent.includes(reference)))
    .sort((left, right) => Math.max(...right.references.map((reference) => reference.length))
      - Math.max(...left.references.map((reference) => reference.length)))[0]?.asset ?? null;
  const aircraft = referencedAsset(assetLibrary.aircraft) ?? workspace.aircraft;
  const mapPack = referencedAsset(assetLibrary.maps) ?? workspace.mapPack;
  if (aircraft.id === workspace.aircraft.id && mapPack.id === workspace.mapPack.id) return workspace;
  const updatedAt = new Date().toISOString();
  return updatedWorkspace(workspace, {
    aircraft,
    mapPack,
    mission: {
      ...workspace.mission,
      aircraftProfileId: aircraft.id,
      mapPackId: mapPack.id,
      compiledPlan: null,
      updatedAt,
    },
  });
}

function missionPlanSnapshot(
  response: AutonomyCompileResponse,
  workspace: AutonomyWorkspaceState,
  source: AutonomyMissionPlanSnapshot["source"],
  plannerBinding: AutonomyCompileAssetContext["planner_binding"],
): AutonomyMissionPlanSnapshot {
  const aircraftReady = isAutonomyAircraftProfileValid(workspace.aircraft);
  const mapReady = autonomyMapPackQualified(workspace.mapPack);
  const assetIssues: AutonomyMissionPlanSnapshot["issues"] = [
    ...(!aircraftReady ? [{
      code: "asset.aircraft.not-qualified",
      severity: "error" as const,
      message: "The selected Vehicle Pack does not pass its task-specific flight-envelope checks.",
    }] : []),
    ...(!mapReady ? [{
      code: "asset.map.not-qualified",
      severity: "error" as const,
      message: "The selected Map Pack is not calibrated and bound to a compiled three-dimensional scene.",
    }] : []),
  ];
  const assetsReady = aircraftReady && mapReady;
  const authoritative = source === "backend";
  return {
    schemaVersion: 1,
    source,
    contractId: response.contract.contract_id,
    sceneId: response.scene.id,
    sceneName: response.scene.name,
    feasible: response.feasible && assetsReady && authoritative,
    readiness: assetsReady && authoritative ? response.execution_policy.readiness : "denied",
    canExecute: assetsReady && authoritative && response.execution_policy.can_execute,
    perceptionMode: response.contract.perception_mode,
    plannerBinding,
    steps: response.contract.steps.map((step) => ({
      order: step.order,
      action: step.action,
      label: step.label,
      payloadDeltaKg: step.payload_delta_kg,
    })),
    taskGraph: response.contract.task_graph,
    issues: [...assetIssues, ...response.issues],
    metrics: {
      routeLengthM: response.metrics.route_length_m,
      verticalTravelM: response.metrics.vertical_travel_m,
      estimatedDurationS: response.metrics.estimated_duration_s,
      minimumClearanceM: response.metrics.minimum_clearance_m,
      launchMassKg: response.metrics.launch_mass_kg,
      postPickupMassKg: response.metrics.post_pickup_mass_kg,
      postPickupThrustToWeight: response.metrics.post_pickup_thrust_to_weight,
      brakingDistanceM: response.metrics.braking_distance_m,
    },
    immutableSafetyRules: response.contract.immutable_safety_rules,
    compiledAt: new Date().toISOString(),
  };
}

function AutonomyMissionPlanCard({
  chinese,
  workspace,
}: {
  chinese: boolean;
  workspace: AutonomyWorkspaceState;
}) {
  const plan = workspace.mission.compiledPlan;
  if (!plan) return null;
  const blockingIssues = plan.issues.filter((issue) => issue.severity === "error");
  return (
    <section className="autonomy-inline-plan" aria-live="polite">
      <header>
        <span><Waypoints aria-hidden="true" /></span>
        <div>
          <small>{chinese ? "自动生成的任务计划" : "Generated mission plan"}</small>
          <h3>{workspace.mission.intent}</h3>
        </div>
        <em className={plan.canExecute ? "is-ready" : "is-blocked"}>
          {plan.canExecute ? (chinese ? "可进入仿真" : "Simulation ready") : (chinese ? "需要处理" : "Action required")}
        </em>
      </header>
      <div className="autonomy-inline-plan-bindings">
        <span><Navigation2 aria-hidden="true" /><small>{chinese ? "无人机" : "Aircraft"}</small><strong>{workspace.aircraft.name} · v{workspace.aircraft.version}</strong></span>
        <span><Layers3 aria-hidden="true" /><small>{chinese ? "地图" : "Map"}</small><strong>{workspace.mapPack.name}</strong></span>
        <span><Radar aria-hidden="true" /><small>{chinese ? "感知" : "Perception"}</small><strong>{plan.perceptionMode.toUpperCase()}</strong></span>
        <span><Route aria-hidden="true" /><small>{chinese ? "路线" : "Route"}</small><strong>{plan.metrics.routeLengthM.toFixed(1)} m · {Math.ceil(plan.metrics.estimatedDurationS)} s</strong></span>
      </div>
      {blockingIssues.length ? <ul className="autonomy-inline-plan-issues">{blockingIssues.map((issue) => <li key={issue.code}><ShieldCheck aria-hidden="true" /><span>{issue.message}</span></li>)}</ul> : null}
      <details className="autonomy-task-graph" open>
        <summary>
          <span>{chinese ? "执行任务树" : "Execution task graph"}</span>
          <small>{plan.taskGraph.nodes.length} {chinese ? "个可审计节点" : "auditable nodes"}</small>
        </summary>
        <ol>
          {plan.taskGraph.nodes.map((node, index) => <li key={node.task_id} data-risk={node.risk}>
            <i>{String(index + 1).padStart(2, "0")}</i>
            <div>
              <strong>{node.label}</strong>
              <span>{node.executor.replaceAll("_", " ")} · {node.risk.toUpperCase()} · {node.timeout_s}s · {chinese ? "失败" : "fallback"} {node.fallback.toUpperCase()}</span>
              <small>{chinese ? "证据" : "Evidence"}: {node.completion_evidence.join(" · ")}</small>
            </div>
          </li>)}
        </ol>
      </details>
      <footer>
        <span>{plan.source === "backend" ? (chinese ? "后端合同" : "Backend contract") : (chinese ? "本地安全预览" : "Local safety preview")} · {plan.contractId}</span>
        <div>
          <Link className="btn" to="/autonomy/aircraft">{chinese ? "无人机" : "Aircraft"}</Link>
          <Link className="btn" to="/autonomy/maps">{chinese ? "地图" : "Maps"}</Link>
          {plan.canExecute ? <Link className="btn btn-primary" to="/autonomy/live"><Airplay aria-hidden="true" />{chinese ? "进入仿真" : "Open simulation"}</Link> : null}
        </div>
      </footer>
    </section>
  );
}

export function AutonomyPlatform() {
  const auth = useOptionalAuth();
  const theme = useEditionTheme();
  const location = useLocation();
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN" || interfaceLocale === "zh-TW";
  const copy = chinese ? SECTION_COPY.zh : SECTION_COPY.en;
  const ownerId = auth?.account?.id ?? "local";
  const edition = theme.id;
  const [workspace, setWorkspace] = useState(() => loadAutonomyWorkspace(ownerId, edition));
  const [assetLibrary, setAssetLibrary] = useState(() => {
    const current = loadAutonomyWorkspace(ownerId, edition);
    return loadAutonomyAssetLibrary(ownerId, edition, current);
  });
  const [missionComposerDraft, setMissionComposerDraft] = useState("");
  const bundledQualificationAttempt = useRef<string | null>(null);

  useEffect(() => {
    const next = loadAutonomyWorkspace(ownerId, edition);
    setWorkspace(next);
    setAssetLibrary(loadAutonomyAssetLibrary(ownerId, edition, next));
    setMissionComposerDraft("");
  }, [edition, ownerId]);

  const persist = useCallback((next: AutonomyWorkspaceState) => {
    const saved = saveAutonomyWorkspace(ownerId, edition, next);
    setWorkspace(saved);
    setAssetLibrary((current) => saveAutonomyAssetLibrary(
      ownerId,
      edition,
      withCurrentAutonomyAssets(current, saved),
    ));
  }, [edition, ownerId]);

  useEffect(() => {
    const officialAircraftSelected = workspace.aircraft.id === "aircraft-my-drone";
    const officialMapSelected = workspace.mapPack.id === "map-school";
    const aircraftNeedsQualification = officialAircraftSelected
      && (workspace.aircraft.status === "draft"
        || !workspace.aircraft.qualificationReceiptId
        || !workspace.aircraft.qualificationContentHash);
    const mapNeedsQualification = officialMapSelected
      && (workspace.mapPack.status !== "qualified"
        || !workspace.mapPack.qualificationReceiptId
        || !workspace.mapPack.contentHash);
    if (
      publicDemoConsole
      || !auth?.account?.id
      || (!aircraftNeedsQualification && !mapNeedsQualification)
    ) return undefined;
    const attemptKey = [
      ownerId,
      workspace.aircraft.updatedAt,
      workspace.mapPack.updatedAt,
      aircraftNeedsQualification,
      mapNeedsQualification,
    ].join(":");
    if (bundledQualificationAttempt.current === attemptKey) return undefined;
    bundledQualificationAttempt.current = attemptKey;
    let cancelled = false;
    void Promise.all([
      aircraftNeedsQualification
        ? apiClient.qualifyAutonomyVehiclePack(vehicleQualificationRequest(workspace.aircraft))
        : Promise.resolve(null),
      mapNeedsQualification
        ? apiClient.qualifyAutonomyMapPack(mapQualificationRequest(workspace.mapPack))
        : Promise.resolve(null),
    ]).then(([aircraftReceipt, mapReceipt]) => {
      if (cancelled) return;
      if (aircraftReceipt && aircraftReceipt.status !== "validated_unsigned") return;
      if (mapReceipt && mapReceipt.status !== "qualified") return;
      const updatedAt = new Date().toISOString();
      const aircraft = aircraftReceipt ? {
        ...workspace.aircraft,
        status: "validated-unsigned" as const,
        qualificationReceiptId: aircraftReceipt.receipt_id,
        qualificationContentHash: aircraftReceipt.content_sha256,
        updatedAt,
      } : workspace.aircraft;
      const mapPack = mapReceipt ? {
        ...workspace.mapPack,
        status: "qualified" as const,
        qualificationReceiptId: mapReceipt.receipt_id,
        contentHash: mapReceipt.content_sha256,
        updatedAt,
      } : workspace.mapPack;
      persist(updatedWorkspace(workspace, {
        aircraft,
        mapPack,
        mission: {
          ...workspace.mission,
          aircraftProfileId: aircraft.id,
          mapPackId: mapPack.id,
          compiledPlan: null,
          updatedAt,
        },
      }));
    }).catch(() => {
      // The existing qualification surfaces remain the explicit retry path.
    });
    return () => {
      cancelled = true;
    };
  }, [auth?.account?.id, ownerId, persist, workspace]);

  const selectAircraft = useCallback((aircraftId: string) => {
    const aircraft = assetLibrary.aircraft.find((candidate) => candidate.id === aircraftId);
    if (!aircraft || aircraft.id === workspace.aircraft.id) return;
    const updatedAt = new Date().toISOString();
    persist(updatedWorkspace(workspace, {
      aircraft,
      mission: {
        ...workspace.mission,
        aircraftProfileId: aircraft.id,
        compiledPlan: null,
        updatedAt,
      },
    }));
  }, [assetLibrary.aircraft, persist, workspace]);

  const selectMap = useCallback((mapId: string) => {
    const mapPack = assetLibrary.maps.find((candidate) => candidate.id === mapId);
    if (!mapPack || mapPack.id === workspace.mapPack.id) return;
    const updatedAt = new Date().toISOString();
    persist(updatedWorkspace(workspace, {
      mapPack,
      mission: {
        ...workspace.mission,
        mapPackId: mapPack.id,
        compiledPlan: null,
        updatedAt,
      },
    }));
  }, [assetLibrary.maps, persist, workspace]);

  const sections: Array<{ id: AutonomySectionId; to: string }> = [
    { id: "overview", to: "/autonomy" },
    { id: "aircraft", to: "/autonomy/aircraft" },
    { id: "maps", to: "/autonomy/maps" },
    { id: "live", to: "/autonomy/live" },
    { id: "evidence", to: "/autonomy/evidence" },
  ];
  const currentSectionPath = normalizedAutonomyPath(location.pathname);

  return (
    <div className="autonomy-platform-page">
      <header className="autonomy-platform-header">
        <h1>{copy.title}</h1>
        <nav className="autonomy-section-switch" aria-label={copy.title}>
          {sections.map(({ id, to }) => {
            const Icon = SECTION_ICONS[id];
            const selected = currentSectionPath === to;
            return (
              <NavLink
                key={id}
                to={to}
                end={id === "overview"}
                className={({ isActive }) => isActive || selected ? "active" : undefined}
                aria-current={selected ? "page" : undefined}
              >
                <Icon aria-hidden="true" />
                <span>{copy[id]}</span>
              </NavLink>
            );
          })}
        </nav>
      </header>

      <main className="autonomy-platform-content">
        <Outlet context={{
          edition,
          chinese,
          workspace,
          assetLibrary,
          persist,
          selectAircraft,
          selectMap,
          missionComposerDraft,
          setMissionComposerDraft,
        } satisfies WorkspaceContext} />
      </main>
    </div>
  );
}

export function AutonomyOverview() {
  const {
    edition,
    chinese,
    workspace,
    assetLibrary,
    selectAircraft,
    selectMap,
    persist,
    missionComposerDraft: composer,
    setMissionComposerDraft: setComposer,
  } = useAutonomyWorkspace();
  const auth = useOptionalAuth();
  const {
    settings: modelAccess,
    profiles: modelProfiles,
    activeProfileId,
    selectAccessMode,
    selectManagedModel,
    selectProfile,
  } = useModelAccess();
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const [voiceConsentPending, setVoiceConsentPending] = useState(false);
  const [voiceConsentGranted, setVoiceConsentGranted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [managedModels, setManagedModels] = useState(DEFAULT_MANAGED_MODEL_CATALOG);
  const [managedModelsReady, setManagedModelsReady] = useState(true);
  const [generating, setGenerating] = useState(false);
  const contextMenuRef = useRef<HTMLDivElement>(null);
  const configuredProfiles = modelProfiles.filter((profile) => profile.apiKey.trim());
  const selectedManagedModel = managedModels.find(
    (model) => model.provider === modelAccess.managedProvider
      && model.model === modelAccess.managedModel
      && managedModelAvailableForAssistant(model),
  ) ?? null;
  const selectedCustomProfileId = modelAccess.accessMode === "byok"
    && configuredProfiles.some((profile) => profile.id === activeProfileId)
    ? activeProfileId
    : null;
  const selectedPlanningModel = modelAccess.accessMode === "platform"
    ? selectedManagedModel
      ? { accessMode: "platform" as const, provider: selectedManagedModel.provider, model: selectedManagedModel.model }
      : null
    : selectedCustomProfileId && modelAccess.model.trim()
      ? { accessMode: "byok" as const, provider: modelAccess.provider, model: modelAccess.model.trim() }
      : null;
  const copy = chinese ? {
    question: "你希望无人机完成什么任务？",
    placeholder: "描述目标、途经点、环境和需要完成的工作…",
    workflow: "自主飞行任务",
    context: "任务上下文",
    aircraft: "当前无人机",
    map: "当前地图",
    selected: "已选择",
    edit: "管理",
    send: "生成任务合同",
    model: "模型",
    microphone: "使用语音输入",
    stopVoice: "停止语音输入",
    requestingVoice: "正在请求麦克风权限…",
    listening: "正在聆听…",
    voiceConsent: "浏览器可能使用语音服务转写麦克风音频；音频不会写入任务合同。",
    startVoice: "允许并开始",
    cancelVoice: "取消",
    voiceUnavailable: "当前环境无法使用语音输入，你仍可继续输入文字。",
    tooLong: "任务描述不能超过 2,000 个字符。",
    modelUnavailable: "请先选择可用于任务规划的模型。",
    modelFallback: "模型推理暂时不可用；系统已使用确定性安全编译器生成可审阅计划。",
    followUpPlaceholder: "继续补充地点、载荷、路线或安全要求…",
    deterministicPlanReply: "我已根据当前绑定的无人机、地图和安全约束生成可审阅的任务计划。你可以继续提出修改，我会在同一对话中更新任务合同与执行任务树。",
    examples: [
      { title: "办公室取物", body: "从办公室起飞，避开走廊和楼梯中的人员，前往取物点，确认载荷后安全返航。" },
      { title: "视觉巡检", body: "沿指定区域自主巡检，使用实时视觉识别目标与动态障碍，并报告每个检查点的进度。" },
      { title: "未知环境探索", body: "只给定起点和终点，边飞行边建立局部地图，规划安全航迹并在环境变化时实时重规划。" },
    ],
  } : {
    question: "What should your drone do?",
    placeholder: "Describe the goal, waypoints, environment, and work to complete…",
    workflow: "Autonomous mission",
    context: "Mission context",
    aircraft: "Current aircraft",
    map: "Current map",
    selected: "Selected",
    edit: "Manage",
    send: "Build mission contract",
    model: "Model",
    microphone: "Use voice input",
    stopVoice: "Stop voice input",
    requestingVoice: "Requesting microphone access…",
    listening: "Listening…",
    voiceConsent: "Your browser may use a speech service to transcribe microphone audio. Audio is not written to the mission contract.",
    startVoice: "Allow and start",
    cancelVoice: "Cancel",
    voiceUnavailable: "Voice input is unavailable here. You can keep typing.",
    tooLong: "The mission description must stay within 2,000 characters.",
    modelUnavailable: "Choose an available planning model before continuing.",
    modelFallback: "Model reasoning was unavailable; the deterministic safety compiler generated a reviewable plan.",
    followUpPlaceholder: "Add a location, payload, route, or safety requirement…",
    deterministicPlanReply: "I generated a reviewable mission plan from the bound aircraft, map, and safety constraints. Continue with any changes and I will update the mission contract and execution graph in this conversation.",
    examples: [
      { title: "Office pickup", body: "Take off from the office, avoid people in the corridor and stairwell, collect the payload, and return safely." },
      { title: "Visual inspection", body: "Inspect the assigned area with live vision, track dynamic obstacles, and report progress at every checkpoint." },
      { title: "Unknown environment", body: "Use only the start and goal, build a local map in flight, plan a safe route, and replan as the world changes." },
    ],
  };
  const publicWorkspace = defaultAutonomyWorkspace();
  const publicAircraft = assetLibrary.aircraft.find((aircraft) => aircraft.id === publicWorkspace.aircraft.id)
    ?? publicWorkspace.aircraft;
  const publicMap = assetLibrary.maps.find((mapPack) => mapPack.id === publicWorkspace.mapPack.id)
    ?? publicWorkspace.mapPack;
  const appendTranscript = useCallback((transcript: string) => {
    setComposer((current) => {
      const next = current.trim() ? `${current.trim()} ${transcript}` : transcript;
      return next.slice(0, 2_000);
    });
  }, [setComposer]);
  const voice = useVoiceInput({ locale: chinese ? "zh-CN" : "en", onTranscript: appendTranscript });
  const conversationActive = workspace.mission.messages.length > 0 || Boolean(workspace.mission.compiledPlan);
  const conversationMessages: AutonomyConversationMessage[] = workspace.mission.messages.length
    ? workspace.mission.messages
    : workspace.mission.compiledPlan
      ? [
          {
            id: "migrated-user-message",
            role: "user",
            content: workspace.mission.intent,
            createdAt: workspace.mission.updatedAt,
            planContractId: null,
          },
          {
            id: "migrated-assistant-message",
            role: "assistant",
            content: workspace.mission.planningBrief || copy.deterministicPlanReply,
            createdAt: workspace.mission.updatedAt,
            planContractId: workspace.mission.compiledPlan.contractId,
          },
        ]
      : [];

  useEffect(() => {
    if (!auth?.account) {
      setManagedModels(DEFAULT_MANAGED_MODEL_CATALOG);
      setManagedModelsReady(true);
      return;
    }
    let active = true;
    setManagedModelsReady(false);
    void getManagedModelCatalog()
      .then((catalog) => {
        if (!active) return;
        setManagedModels(completeManagedModelCatalog(catalog.models));
        setManagedModelsReady(true);
      })
      .catch(() => {
        if (!active) return;
        setManagedModels(DEFAULT_MANAGED_MODEL_CATALOG);
        setManagedModelsReady(true);
      });
    return () => {
      active = false;
    };
  }, [auth?.account]);

  useEffect(() => {
    if (
      modelAccess.accessMode !== "platform"
      || selectedManagedModel
      || !managedModelsReady
    ) return;
    const fallback = managedModels.find(managedModelAvailableForAssistant);
    if (fallback) selectManagedModel(fallback.provider, fallback.model);
  }, [
    managedModels,
    managedModelsReady,
    modelAccess.accessMode,
    selectManagedModel,
    selectedManagedModel,
  ]);

  useEffect(() => {
    if (!contextMenuOpen) return undefined;
    const closeOnOutside = (event: PointerEvent) => {
      if (!contextMenuRef.current?.contains(event.target as Node)) setContextMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setContextMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [contextMenuOpen]);

  const submitMission = async (event: FormEvent) => {
    event.preventDefault();
    const intent = composer.trim();
    if (!intent) return;
    if (intent.length > 2_000) {
      setError(copy.tooLong);
      return;
    }
    if (!selectedPlanningModel || generating) {
      setError(copy.modelUnavailable);
      return;
    }
    voice.cancel();
    consumeAutonomyHandoff();
    setGenerating(true);
    setError(null);
    try {
      const missionWorkspace = resolveMissionAssets(workspace, assetLibrary, intent);
      const assistantWorkspaceId = missionWorkspace.mission.conversationId ?? createExperimentWorkspaceId();
      const turnId = crypto.randomUUID();
      const followUpPrefix = chinese ? "\n补充指令：" : "\nFollow-up instruction: ";
      const revisedIntent = missionWorkspace.mission.messages.length || missionWorkspace.mission.compiledPlan
        ? `${missionWorkspace.mission.intent.slice(0, Math.max(0, 2_000 - followUpPrefix.length - intent.length))}${followUpPrefix}${intent}`
        : intent;
      const submittedAt = new Date().toISOString();
      const userMessage: AutonomyConversationMessage = {
        id: `user-${turnId}`,
        role: "user",
        content: intent,
        createdAt: submittedAt,
        planContractId: null,
      };
      const priorMessages = missionWorkspace.mission.messages;
      persist(updatedWorkspace(missionWorkspace, {
        mission: {
          ...missionWorkspace.mission,
          intent: revisedIntent,
          conversationId: assistantWorkspaceId,
          messages: [...priorMessages, userMessage].slice(-100),
          aircraftProfileId: missionWorkspace.aircraft.id,
          mapPackId: missionWorkspace.mapPack.id,
          updatedAt: submittedAt,
        },
      }));
      setComposer("");
      const harnessRequest = autonomyHarnessRequest(edition, missionWorkspace, revisedIntent);
      let harnessInspection: AutonomyHarnessInspectResponse;
      harnessInspection = publicDemoConsole
        ? await localAutonomyHarnessInspection(harnessRequest)
        : await apiClient.inspectAutonomyHarness(harnessRequest);
      let planningBrief = "";
      let planningRunId: string | null = assistantWorkspaceId;
      let planningArtifactSha256: string | null = null;
      let autonomyArtifact: AutonomyPlannerArtifact | null = null;
      if (!publicDemoConsole) {
        try {
          const workflow = await apiClient.compileTaskWorkflow({
            request_id: `autonomy:${assistantWorkspaceId}:${turnId}`,
            edition,
            requested_task_type: "mission_autonomy",
            message: intent,
            locale: chinese ? "zh-CN" : "en",
            conversation_summary: missionWorkspace.mission.planningBrief.slice(0, 4_000),
            context: [
              {
                key: "autonomy.harness",
                value: JSON.stringify(
                  autonomyModelContext(harnessRequest, harnessInspection),
                ).slice(0, 4_000),
                source: "asset_receipt",
              },
              {
                key: "planning.model",
                value: `${selectedPlanningModel.accessMode}:${selectedPlanningModel.provider}:${selectedPlanningModel.model}`,
                source: "workspace",
              },
            ],
            requested_tool_ids: [],
          });
          planningRunId = workflow.contract_id;
          if (workflow.status === "blocked") {
            harnessInspection = {
              ...harnessInspection,
              status: "blocked",
              planning_ready: false,
              blockers: [...new Set([
                ...harnessInspection.blockers,
                ...workflow.blockers,
              ])],
            };
            planningBrief = autonomyAssetBlockerMessage(harnessInspection, chinese);
          }
        } catch {
          harnessInspection = {
            ...harnessInspection,
            status: "blocked",
            planning_ready: false,
            blockers: [...new Set([
              ...harnessInspection.blockers,
              "The deterministic task workflow could not be compiled.",
            ])],
          };
          planningBrief = autonomyAssetBlockerMessage(harnessInspection, chinese);
        }
      }
      try {
        if (!harnessInspection.planning_ready) {
          throw new Error("The deterministic workflow gate blocked model planning.");
        }
        if (selectedPlanningModel.accessMode !== "platform") {
          throw new Error("The dedicated BYOK autonomy planner adapter is not yet bound.");
        }
        const response = (await orchestrateAssistantTurn({
            edition,
            workspaceId: assistantWorkspaceId,
            organizationId: activeAssistantTenantContext(auth?.account?.id ?? "local").organizationId,
            idempotencyKey: `autonomy:${assistantWorkspaceId}:${turnId}`,
            message: intent,
            requestedTaskType: "mission_autonomy",
            locale: chinese ? "zh-CN" : "en",
            selectedModel: selectedPlanningModel,
            currentValues: {
              autonomy_context: autonomyModelContext(harnessRequest, harnessInspection),
            },
            documentContext: null,
          })).response;
        autonomyArtifact = parseAutonomyPlannerArtifact(
          response.orchestration?.artifact_payload,
        );
        if (!autonomyArtifact) {
          throw new Error("The model did not return a valid autonomy planner artifact.");
        }
        const serverArtifactSha256 = response.orchestration?.artifact_sha256;
        const localArtifactSha256 = await autonomyCanonicalSha256(autonomyArtifact);
        if (
          !serverArtifactSha256
          || !/^[0-9a-f]{64}$/u.test(serverArtifactSha256)
          || serverArtifactSha256 !== localArtifactSha256
        ) {
          throw new Error("The model planner artifact did not match its server-issued digest.");
        }
        planningArtifactSha256 = serverArtifactSha256;
        const plannerBindingIssues = autonomyPlannerBindingIssues(
          autonomyArtifact,
          harnessRequest,
          harnessInspection,
        );
        if (plannerBindingIssues.length > 0) {
          throw new Error(`The model planner artifact failed binding: ${plannerBindingIssues.join(", ")}`);
        }
        planningBrief = !harnessInspection.planning_ready
          ? autonomyAssetBlockerMessage(harnessInspection, chinese)
          : response.assistant_message?.trim() || response.experiment_summary.trim();
        if (autonomyArtifact.status !== "draft") {
          harnessInspection = {
            ...harnessInspection,
            status: autonomyArtifact.status,
            planning_ready: false,
            blockers: [...new Set([
              ...harnessInspection.blockers,
              ...autonomyArtifact.blockers,
            ])],
          };
        }
        planningRunId = response.orchestration?.run_id ?? planningRunId;
      } catch (reason) {
        planningBrief = planningBrief || autonomyAssetBlockerMessage(harnessInspection, chinese);
        if (!publicDemoConsole) {
          throw reason instanceof Error
            ? reason
            : new Error("The model planner did not produce a bound mission draft.");
        }
      }
      if (!harnessInspection.planning_ready) {
        const updatedAt = new Date().toISOString();
        const assistantMessage: AutonomyConversationMessage = {
          id: `assistant-${turnId}`,
          role: "assistant",
          content: planningBrief,
          createdAt: updatedAt,
          planContractId: null,
        };
        persist(updatedWorkspace(missionWorkspace, {
          mission: {
            ...missionWorkspace.mission,
            intent: revisedIntent,
            planningModel: selectedPlanningModel,
            planningBrief,
            planningRunId,
            conversationId: assistantWorkspaceId,
            messages: [...priorMessages, userMessage, assistantMessage].slice(-100),
            aircraftProfileId: missionWorkspace.aircraft.id,
            mapPackId: missionWorkspace.mapPack.id,
            compiledPlan: null,
            currentStep: 0,
            updatedAt,
          },
        }));
        return;
      }
      const compileRequest = compileRequestForWorkspace(
        edition,
        missionWorkspace,
        revisedIntent,
        {
          schema_version: "dronedream.autonomy.compile-assets.v1",
          harness_context_sha256: harnessInspection.context_sha256,
          aircraft: harnessRequest.aircraft,
          map_pack: harnessRequest.map_pack,
          planner_binding: publicDemoConsole || !autonomyArtifact || !planningRunId
            || !planningArtifactSha256
            ? null
            : {
                schema_version: "dronedream.autonomy.planner-binding.v1",
                status: "draft",
                run_id: planningRunId,
                provider: selectedPlanningModel.provider,
                model: selectedPlanningModel.model,
                artifact_sha256: planningArtifactSha256,
                goal: autonomyArtifact.goal,
                aircraft_id: autonomyArtifact.asset_bindings.aircraft_id,
                aircraft_version: autonomyArtifact.asset_bindings.aircraft_version,
                map_id: autonomyArtifact.asset_bindings.map_id,
                map_version: autonomyArtifact.asset_bindings.map_version,
                context_sha256: autonomyArtifact.asset_bindings.context_sha256,
                task_graph: autonomyArtifact.task_graph,
              },
        },
      );
      const localMissionId = missionIdForScene(compileRequest.scene_id, compileRequest.natural_language);
      let compileResult: AutonomyCompileResponse;
      let compileSource: AutonomyMissionPlanSnapshot["source"];
      if (!publicDemoConsole) {
        compileResult = await apiClient.compileAutonomyMission(compileRequest);
        compileSource = "backend";
      } else {
        compileResult = createLocalAutonomyPreview(localMissionId, compileRequest);
        compileSource = "local-preview";
      }
      const updatedAt = new Date().toISOString();
      const compiledPlan = missionPlanSnapshot(
        compileResult,
        missionWorkspace,
        compileSource,
        compileRequest.asset_context?.planner_binding ?? null,
      );
      const assistantMessage: AutonomyConversationMessage = {
        id: `assistant-${turnId}`,
        role: "assistant",
        content: planningBrief || copy.deterministicPlanReply,
        createdAt: updatedAt,
        planContractId: compiledPlan.contractId,
      };
      persist(updatedWorkspace(missionWorkspace, {
        mission: {
          ...missionWorkspace.mission,
          intent: revisedIntent,
          planningModel: selectedPlanningModel,
          planningBrief,
          planningRunId,
          conversationId: assistantWorkspaceId,
          messages: [...priorMessages, userMessage, assistantMessage].slice(-100),
          aircraftProfileId: missionWorkspace.aircraft.id,
          mapPackId: missionWorkspace.mapPack.id,
          compiledPlan,
          currentStep: 0,
          updatedAt,
        },
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : copy.modelUnavailable);
    } finally {
      setGenerating(false);
    }
  };

  const voiceStatus = voice.state === "requesting"
    ? copy.requestingVoice
    : voice.state === "listening"
      ? copy.listening
      : voice.error
        ? copy.voiceUnavailable
        : null;

  return (
    <section className={`autonomy-command-page ${conversationActive ? "is-conversation" : ""}`} data-grants-hardware-authority="false">
      <div className={`autonomy-command-stage ${conversationActive ? "is-conversation" : ""}`}>
        {conversationActive ? (
          <div className="autonomy-conversation-scroll">
            <div className="autonomy-conversation-thread" aria-live="polite">
              {conversationMessages.map((message) => (
                <article className={`autonomy-conversation-message is-${message.role}`} key={message.id}>
                  {message.role === "assistant" ? (
                    <span className="autonomy-conversation-avatar" aria-hidden="true"><Sparkles /></span>
                  ) : null}
                  <div className="autonomy-conversation-body">
                    <p>{message.content}</p>
                    {message.role === "assistant"
                      && workspace.mission.compiledPlan
                      && message.planContractId === workspace.mission.compiledPlan.contractId
                      ? <AutonomyMissionPlanCard chinese={chinese} workspace={workspace} />
                      : null}
                  </div>
                  {message.role === "user" ? (
                    <span className="autonomy-conversation-avatar is-user-account" aria-label={auth?.account?.displayName ?? (chinese ? "本地用户" : "Local user")}>
                      {auth?.account?.avatarUrl ? (
                        <img src={auth.account.avatarUrl} alt="" />
                      ) : auth?.account?.displayName ? (
                        auth.account.displayName.slice(0, 1).toLocaleUpperCase()
                      ) : (
                        <CircleUserRound aria-hidden="true" />
                      )}
                    </span>
                  ) : null}
                </article>
              ))}
              {generating ? (
                <article className="autonomy-conversation-message is-assistant is-generating" aria-label={chinese ? "正在生成任务计划" : "Generating mission plan"}>
                  <span className="autonomy-conversation-avatar" aria-hidden="true"><Sparkles /></span>
                  <div className="autonomy-conversation-thinking"><i /><i /><i /></div>
                </article>
              ) : null}
            </div>
          </div>
        ) : (
          <>
            <div className="assistant-hero-icon autonomy-command-hero-icon" aria-hidden="true">
              <AutonomyCloudTerminalIcon />
            </div>
            <h2>{copy.question}</h2>
            <div className="assistant-examples autonomy-command-examples">
              {copy.examples.map((example, index) => (
                <button type="button" key={example.title} onClick={() => setComposer(example.body)}>
                  <span className="assistant-example-heading">
                    <AutonomyTemplateIcon index={index} />
                    <strong>{example.title}</strong>
                  </span>
                  <span className="assistant-example-body">{example.body}</span>
                </button>
              ))}
            </div>
          </>
        )}
        <form className="assistant-composer autonomy-command-composer" onSubmit={submitMission}>
          <textarea
            value={composer}
            maxLength={2_000}
            rows={conversationActive ? 2 : 3}
            placeholder={conversationActive ? copy.followUpPlaceholder : copy.placeholder}
            aria-label={conversationActive ? copy.followUpPlaceholder : copy.placeholder}
            onChange={(event) => {
              setComposer(event.target.value);
              setError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <div className="assistant-composer-bar">
            <div className="assistant-add-menu" ref={contextMenuRef}>
              <button
                type="button"
                className="assistant-add-button"
                aria-label={copy.context}
                title={copy.context}
                aria-haspopup="dialog"
                aria-expanded={contextMenuOpen}
                onClick={() => setContextMenuOpen((current) => !current)}
              >
                <Plus aria-hidden="true" strokeWidth={1.8} />
              </button>
              {contextMenuOpen ? (
                <div className="assistant-add-popover autonomy-context-popover" role="dialog" aria-label={copy.context}>
                  <strong className="assistant-task-popover-title">{copy.context}</strong>
                  <section className="autonomy-context-group" aria-label={copy.aircraft}>
                    <header><span><Navigation2 aria-hidden="true" />{copy.aircraft}</span><Link to="/autonomy/aircraft" onClick={() => setContextMenuOpen(false)}>{copy.edit}</Link></header>
                    {[publicAircraft].map((aircraft) => <label className="autonomy-context-asset" key={aircraft.id}>
                      <input type="radio" name="autonomy-aircraft" value={aircraft.id} checked={aircraft.id === workspace.aircraft.id} onChange={() => selectAircraft(aircraft.id)} />
                      <span><b>{aircraft.name}</b><small>{aircraft.airframe} · GPS · {aircraft.controlInterface.toUpperCase()}</small></span>
                      {aircraft.id === workspace.aircraft.id ? <em>{copy.selected}</em> : null}
                    </label>)}
                  </section>
                  <section className="autonomy-context-group" aria-label={copy.map}>
                    <header><span><Layers3 aria-hidden="true" />{copy.map}</span><Link to="/autonomy/maps" onClick={() => setContextMenuOpen(false)}>{copy.edit}</Link></header>
                    {[publicMap].map((mapPack) => <label className="autonomy-context-asset" key={mapPack.id}>
                      <input type="radio" name="autonomy-map" value={mapPack.id} checked={mapPack.id === workspace.mapPack.id} onChange={() => selectMap(mapPack.id)} />
                      <span><b>{mapPack.name}</b><small>{mapPack.representation} · {mapPack.coordinateFrame}</small></span>
                      {mapPack.id === workspace.mapPack.id ? <em>{copy.selected}</em> : null}
                    </label>)}
                  </section>
                </div>
              ) : null}
            </div>
            <span className="assistant-task-chip is-explicit"><Route aria-hidden="true" />{copy.workflow}</span>
            <span className="assistant-composer-spacer" />
            <AssistantModelPicker
              ariaLabel={copy.model}
              defaultModels={managedModels}
              customProfiles={configuredProfiles}
              selectedDefault={modelAccess.accessMode === "platform" ? selectedManagedModel : null}
              selectedCustomId={selectedCustomProfileId}
              disabled={!managedModelsReady}
              onSelectDefault={(model) => {
                selectAccessMode("platform");
                selectManagedModel(model.provider, model.model);
              }}
              onSelectCustom={(profileId) => {
                selectProfile(profileId);
                selectAccessMode("byok");
              }}
              onOpenSettings={openAppSettings}
            />
            <button
              type="button"
              className={`assistant-voice-button ${voice.state === "listening" ? "listening" : ""}`}
              aria-label={voice.state === "listening" ? copy.stopVoice : copy.microphone}
              title={voice.state === "listening" ? copy.stopVoice : copy.microphone}
              onClick={() => {
                if (voice.state === "listening") {
                  voice.stop();
                  return;
                }
                if (!voice.supported) {
                  void voice.start();
                  return;
                }
                if (!voiceConsentGranted) {
                  setVoiceConsentPending(true);
                  return;
                }
                void voice.start();
              }}
            >
              <Mic aria-hidden="true" strokeWidth={1.9} />
            </button>
            <button
              type="submit"
              className="assistant-send-button"
              disabled={!composer.trim() || !managedModelsReady || !selectedPlanningModel || generating}
              aria-label={copy.send}
              title={copy.send}
            >
              <ArrowUp aria-hidden="true" strokeWidth={2} />
            </button>
          </div>
          {voiceConsentPending ? (
            <div className="assistant-voice-consent" role="note">
              <p>{copy.voiceConsent}</p>
              <button type="button" className="btn btn-primary" onClick={() => {
                setVoiceConsentPending(false);
                setVoiceConsentGranted(true);
                void voice.start();
              }}>{copy.startVoice}</button>
              <button type="button" className="btn" onClick={() => setVoiceConsentPending(false)}>{copy.cancelVoice}</button>
            </div>
          ) : null}
          {voiceStatus ? <p className="assistant-composer-status">{voiceStatus}</p> : null}
          {error ? <p className="assistant-composer-error" role="alert">{error}</p> : null}
        </form>
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

const AIRCRAFT_MANUFACTURERS = ["Self-built", "DJI", "Holybro", "Auterion", "ModalAI", "CUAV", "Inspired Flight"] as const;
const AIRFRAMES = ["Quad X", "Quad +", "Hex X", "Hex +", "Octo X", "Coaxial Octo", "VTOL"] as const;
const FLIGHT_CONTROLLERS = ["Pixhawk 6C", "Pixhawk 6X", "Cube Orange+", "CUAV X7+", "Auterion Skynode", "ModalAI VOXL 2"] as const;
const COMPUTE_PLATFORMS = ["Jetson Orin NX", "Jetson Orin Nano", "Jetson AGX Orin", "Raspberry Pi 5", "ModalAI VOXL 2"] as const;
const FIRMWARE_BY_AUTOPILOT: Record<AutonomyAircraftProfile["autopilot"], readonly string[]> = {
  px4: ["PX4 v1.16", "PX4 v1.15", "PX4 main"],
  ardupilot: ["ArduPilot Copter 4.6", "ArduPilot Copter 4.5", "ArduPilot master"],
  custom: [],
};
const CUSTOM_FIRMWARE_OPTION = "__custom_firmware__";
const CUSTOM_FLIGHT_CONTROLLER_OPTION = "__custom_flight_controller__";
const CUSTOM_MANUFACTURER_OPTION = "__custom_manufacturer__";
const CUSTOM_AIRFRAME_OPTION = "__custom_airframe__";
const CUSTOM_COMPUTE_OPTION = "__custom_compute__";
const CONTROL_INTERFACES_BY_AUTOPILOT: Record<AutonomyAircraftProfile["autopilot"], readonly AutonomyAircraftProfile["controlInterface"][]> = {
  px4: ["px4-ros2", "mavsdk", "mavlink", "simulation-only"],
  ardupilot: ["mavsdk", "mavlink", "simulation-only"],
  custom: ["mavlink", "simulation-only"],
};
const CONTROL_INTERFACE_LABELS: Record<AutonomyAircraftProfile["controlInterface"], string> = {
  "px4-ros2": "PX4 ROS 2",
  mavsdk: "MAVSDK",
  mavlink: "MAVLink",
  "simulation-only": "Simulation only",
};

function aircraftValidationIssue(aircraft: AutonomyAircraftProfile, chinese: boolean): string | null {
  if (!aircraft.name.trim()) return chinese ? "请填写机型名称" : "Add aircraft name";
  if (!aircraft.manufacturer.trim()) return chinese ? "请选择或填写制造商" : "Select a manufacturer";
  if (!aircraft.airframe.trim() || aircraft.airframe.trim().toLowerCase() === "custom") return chinese ? "请选择或填写机架" : "Select an airframe";
  if (!aircraft.flightController.trim() || aircraft.flightController.trim().toLowerCase() === "custom") return chinese ? "请选择或填写飞控" : "Select a flight controller";
  if (!aircraft.firmware.trim() || aircraft.firmware.trim().toLowerCase() === "custom build") return chinese ? "请选择或填写固件版本" : "Select a firmware build";
  if (!aircraft.computePlatform.trim() || aircraft.computePlatform.trim().toLowerCase() === "custom") return chinese ? "请选择或填写机载计算平台" : "Select onboard compute";

  const outsideLimit = (key: keyof typeof AUTONOMY_AIRCRAFT_LIMITS) => {
    const value = aircraft[key];
    const limit = AUTONOMY_AIRCRAFT_LIMITS[key];
    return typeof value !== "number" || !Number.isFinite(value) || value < limit.min || value > limit.max;
  };
  if ((Object.keys(AUTONOMY_AIRCRAFT_LIMITS) as Array<keyof typeof AUTONOMY_AIRCRAFT_LIMITS>).some(outsideLimit)) {
    return chinese ? "修正红框中的参数" : "Fix highlighted limits";
  }
  if (aircraft.maximumTakeoffMassKg <= aircraft.dryMassKg) return chinese ? "最大起飞重量须大于空机重量" : "Increase MTOM above dry mass";
  if (aircraft.dryMassKg + aircraft.maximumPickupPayloadKg > aircraft.maximumTakeoffMassKg) return chinese ? "降低载荷或提高最大起飞重量" : "Reduce payload or increase MTOM";
  if (autonomyAircraftRadiusM(aircraft) < 0.05) return chinese ? "增大机体或旋翼尺寸" : "Increase body or rotor size";
  if (autonomyAircraftRadiusM(aircraft) > 3) return chinese ? "减小机体或旋翼尺寸" : "Reduce body or rotor size";
  if (aircraft.autopilot !== "px4" && aircraft.controlInterface === "px4-ros2") return chinese ? "控制接口与自动驾驶栈不兼容" : "Choose a compatible control link";
  if (aircraft.commandLink.latencyMs < 0 || aircraft.commandLink.bandwidthMbps <= 0) return chinese ? "修正通信链路参数" : "Fix command-link values";
  if (!aircraft.sensorMounts.some((sensor) => sensor.calibrated && sensor.calibrationStatus === "verified" && (sensor.kind === "gps" || sensor.kind === "vio"))) {
    return chinese ? "验证至少一个 GNSS 或 VIO" : "Verify one GNSS or VIO";
  }
  return null;
}

export function AutonomyAircraft() {
  const { chinese, workspace, assetLibrary, selectAircraft, persist, edition } = useAutonomyWorkspace();
  const [form, setForm] = useState(workspace.aircraft);
  const [saved, setSaved] = useState(false);
  const [qualificationState, setQualificationState] = useState<"idle" | "working" | "qualified" | "blocked" | "unavailable">("idle");
  const [qualificationIssues, setQualificationIssues] = useState<string[]>([]);
  const qualificationReceiptRef = useRef<string | null>(null);
  useEffect(() => {
    setForm(workspace.aircraft);
    const preservesCurrentReceipt = Boolean(workspace.aircraft.qualificationReceiptId)
      && workspace.aircraft.qualificationReceiptId === qualificationReceiptRef.current;
    if (workspace.aircraft.status !== "draft") {
      setQualificationState("qualified");
      setQualificationIssues([]);
    } else if (!preservesCurrentReceipt) {
      setQualificationState("idle");
      setQualificationIssues([]);
    }
  }, [workspace.aircraft]);
  const payloadMargin = form.maximumTakeoffMassKg - form.dryMassKg;
  const thrustToWeight = form.maximumThrustN / (Math.max(form.maximumTakeoffMassKg, 0.01) * 9.80665);
  const valid = isAutonomyAircraftProfileValid(form);
  const validationIssue = aircraftValidationIssue(form, chinese);
  const createAircraft = () => {
    const updatedAt = new Date().toISOString();
    const next: AutonomyAircraftProfile = {
      ...defaultAutonomyWorkspace().aircraft,
      id: `aircraft-${crypto.randomUUID()}`,
      name: chinese ? `新无人机 ${assetLibrary.aircraft.length + 1}` : `New aircraft ${assetLibrary.aircraft.length + 1}`,
      updatedAt,
    };
    persist(updatedWorkspace(workspace, {
      aircraft: next,
      mission: {
        ...workspace.mission,
        aircraftProfileId: next.id,
        compiledPlan: null,
        updatedAt,
      },
    }));
    setSaved(false);
    setQualificationState("idle");
    setQualificationIssues([]);
  };
  const manufacturerIsCustom = !AIRCRAFT_MANUFACTURERS.includes(form.manufacturer as typeof AIRCRAFT_MANUFACTURERS[number]);
  const airframeIsCustom = !AIRFRAMES.includes(form.airframe as typeof AIRFRAMES[number]);
  const flightControllerIsCustom = !FLIGHT_CONTROLLERS.includes(form.flightController as typeof FLIGHT_CONTROLLERS[number]);
  const firmwareOptions = FIRMWARE_BY_AUTOPILOT[form.autopilot];
  const firmwareIsCustom = !firmwareOptions.includes(form.firmware);
  const computePlatformIsCustom = !COMPUTE_PLATFORMS.includes(form.computePlatform as typeof COMPUTE_PLATFORMS[number]);
  const updateAircraft = (patch: Partial<AutonomyAircraftProfile>) => {
    setForm((current) => ({
      ...current,
      ...patch,
      status: "draft",
      qualificationReceiptId: null,
      qualificationContentHash: null,
    }));
    setSaved(false);
    setQualificationState("idle");
    setQualificationIssues([]);
  };
  const numberField = (key: keyof AutonomyAircraftProfile, value: string) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return;
    updateAircraft({ [key]: numeric });
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    if (form.status !== "draft" && form.qualificationReceiptId) return;
    const next = {
      ...form,
      version: Math.max(workspace.aircraft.version + 1, form.version),
      status: "draft" as const,
      qualificationReceiptId: null,
      qualificationContentHash: null,
      updatedAt: new Date().toISOString(),
    };
    persist(updatedWorkspace(workspace, {
      aircraft: next,
      mission: { ...workspace.mission, aircraftProfileId: next.id, updatedAt: next.updatedAt },
    }));
    setSaved(true);
  };
  const toggleSensor = (sensor: AutonomySensorKind) => {
    setForm((current) => ({
      ...current,
      status: "draft",
      qualificationReceiptId: null,
      qualificationContentHash: null,
      sensors: current.sensors.includes(sensor)
        ? current.sensors.filter((item) => item !== sensor)
        : [...current.sensors, sensor],
      sensorMounts: current.sensors.includes(sensor)
        ? current.sensorMounts.filter((item) => item.kind !== sensor)
        : [...current.sensorMounts, {
          id: `${sensor}-${current.sensorMounts.filter((item) => item.kind === sensor).length + 1}`,
          kind: sensor,
          calibrated: false,
          calibrationStatus: "unverified",
          positionM: { x: 0, y: 0, z: 0 },
          rollPitchYawDeg: { x: 0, y: 0, z: 0 },
          rateHz: sensor === "gps" ? 10 : 30,
          calibrationAgeDays: 0,
        }],
    }));
    setSaved(false);
    setQualificationState("idle");
    setQualificationIssues([]);
  };
  const updateSensorMount = (id: string, patch: Partial<AutonomyAircraftProfile["sensorMounts"][number]>) => {
    setForm((current) => ({
      ...current,
      status: "draft",
      qualificationReceiptId: null,
      qualificationContentHash: null,
      sensorMounts: current.sensorMounts.map((sensor) => sensor.id === id ? { ...sensor, ...patch } : sensor),
    }));
    setSaved(false);
    setQualificationState("idle");
    setQualificationIssues([]);
  };
  const qualify = async () => {
    if (!valid) {
      setQualificationState("blocked");
      return;
    }
    if (publicDemoConsole) {
      setQualificationState("unavailable");
      return;
    }
    setQualificationState("working");
    try {
      const receipt = await apiClient.qualifyAutonomyVehiclePack(
        vehicleQualificationRequest(form),
      );
      const next = {
        ...form,
        status: receipt.status === "validated_unsigned" ? "validated-unsigned" as const : "draft" as const,
        qualificationReceiptId: receipt.receipt_id,
        qualificationContentHash: receipt.status === "validated_unsigned" ? receipt.content_sha256 : null,
        updatedAt: new Date().toISOString(),
      };
      qualificationReceiptRef.current = receipt.receipt_id;
      setForm(next);
      persist(updatedWorkspace(workspace, { aircraft: next }));
      setSaved(true);
      setQualificationIssues(receipt.issues.map((issue) => issue.message));
      setQualificationState(receipt.status === "validated_unsigned" ? "qualified" : "blocked");
    } catch {
      setQualificationIssues([]);
      setQualificationState("unavailable");
    }
  };
  return (
    <form className="autonomy-config-page" onSubmit={save}>
      <div className="autonomy-config-main">
        <section className="autonomy-config-card">
          <header><Navigation2 aria-hidden="true" /><h2>{chinese ? "机型身份" : "Aircraft identity"}</h2><div className="autonomy-asset-toolbar"><select aria-label={chinese ? "已保存无人机" : "Saved aircraft"} value={workspace.aircraft.id} onChange={(event) => selectAircraft(event.target.value)}>{assetLibrary.aircraft.map((aircraft) => <option value={aircraft.id} key={aircraft.id}>{aircraft.name} · v{aircraft.version}</option>)}</select><button className="btn" type="button" onClick={createAircraft}><Plus aria-hidden="true" />{chinese ? "新建" : "New"}</button></div></header>
          <div className="autonomy-form-grid is-four autonomy-identity-grid">
            <label><span>{chinese ? "名称" : "Name"}</span><input value={form.name} maxLength={120} onChange={(event) => updateAircraft({ name: event.target.value })} /></label>
            <label><span>{chinese ? "制造商" : "Manufacturer"}</span><div className="autonomy-custom-select-control"><select value={manufacturerIsCustom ? CUSTOM_MANUFACTURER_OPTION : form.manufacturer} onChange={(event) => updateAircraft({ manufacturer: event.target.value === CUSTOM_MANUFACTURER_OPTION ? "" : event.target.value })}>{AIRCRAFT_MANUFACTURERS.map((value) => <option key={value} value={value}>{value}</option>)}<option value={CUSTOM_MANUFACTURER_OPTION}>{chinese ? "其他制造商…" : "Other manufacturer…"}</option></select>{manufacturerIsCustom ? <input value={form.manufacturer.trim().toLowerCase() === "custom" ? "" : form.manufacturer} maxLength={120} placeholder={chinese ? "制造商或自研团队" : "Manufacturer or builder"} aria-label={chinese ? "自定义制造商" : "Custom manufacturer"} onChange={(event) => updateAircraft({ manufacturer: event.target.value })} /> : null}</div></label>
            <label><span>{chinese ? "机架" : "Airframe"}</span><div className="autonomy-custom-select-control"><select value={airframeIsCustom ? CUSTOM_AIRFRAME_OPTION : form.airframe} onChange={(event) => updateAircraft({ airframe: event.target.value === CUSTOM_AIRFRAME_OPTION ? "" : event.target.value })}>{AIRFRAMES.map((value) => <option key={value} value={value}>{value}</option>)}<option value={CUSTOM_AIRFRAME_OPTION}>{chinese ? "自定义机架…" : "Custom airframe…"}</option></select>{airframeIsCustom ? <input value={form.airframe.trim().toLowerCase() === "custom" ? "" : form.airframe} maxLength={120} placeholder={chinese ? "构型、型号或修订" : "Configuration, model, or revision"} aria-label={chinese ? "自定义机架标识" : "Custom airframe identity"} onChange={(event) => updateAircraft({ airframe: event.target.value })} /> : null}</div></label>
            <label><span>{chinese ? "飞控" : "Flight controller"}</span><div className="autonomy-custom-select-control"><select value={flightControllerIsCustom ? CUSTOM_FLIGHT_CONTROLLER_OPTION : form.flightController} onChange={(event) => updateAircraft({ flightController: event.target.value === CUSTOM_FLIGHT_CONTROLLER_OPTION ? "" : event.target.value })}>{FLIGHT_CONTROLLERS.map((value) => <option key={value} value={value}>{value}</option>)}<option value={CUSTOM_FLIGHT_CONTROLLER_OPTION}>{chinese ? "自定义飞控…" : "Custom controller…"}</option></select>{flightControllerIsCustom ? <input value={form.flightController.trim().toLowerCase() === "custom" ? "" : form.flightController} maxLength={120} placeholder={chinese ? "型号与硬件修订" : "Model and hardware revision"} aria-label={chinese ? "自定义飞控标识" : "Custom flight-controller identity"} onChange={(event) => updateAircraft({ flightController: event.target.value })} /> : null}</div></label>
            <label><span>{chinese ? "自动驾驶栈" : "Autopilot"}</span><select value={form.autopilot} onChange={(event) => {
              const autopilot = event.target.value as AutonomyAircraftProfile["autopilot"];
              const compatibleInterfaces = CONTROL_INTERFACES_BY_AUTOPILOT[autopilot];
              const controlInterface = compatibleInterfaces.includes(form.controlInterface)
                ? form.controlInterface
                : compatibleInterfaces[0];
              updateAircraft({ autopilot, firmware: FIRMWARE_BY_AUTOPILOT[autopilot][0] ?? "", controlInterface });
            }}><option value="px4">PX4</option><option value="ardupilot">ArduPilot</option><option value="custom">{chinese ? "自定义" : "Custom"}</option></select></label>
            <label><span>{chinese ? "固件版本" : "Firmware version"}</span><div className="autonomy-custom-select-control"><select value={firmwareIsCustom ? CUSTOM_FIRMWARE_OPTION : form.firmware} onChange={(event) => updateAircraft({ firmware: event.target.value === CUSTOM_FIRMWARE_OPTION ? "" : event.target.value })}>{firmwareOptions.map((value) => <option key={value} value={value}>{value}</option>)}<option value={CUSTOM_FIRMWARE_OPTION}>{chinese ? "自定义构建…" : "Custom build…"}</option></select>{firmwareIsCustom ? <input value={form.firmware.trim().toLowerCase() === "custom build" ? "" : form.firmware} maxLength={120} placeholder={chinese ? "版本、commit 或 build ID" : "Version, commit, or build ID"} aria-label={chinese ? "自定义固件标识" : "Custom firmware identity"} onChange={(event) => updateAircraft({ firmware: event.target.value })} /> : null}</div></label>
            <label><span>{chinese ? "控制接口" : "Control interface"}</span><select value={form.controlInterface} onChange={(event) => updateAircraft({ controlInterface: event.target.value as AutonomyAircraftProfile["controlInterface"] })}>{CONTROL_INTERFACES_BY_AUTOPILOT[form.autopilot].map((value) => <option key={value} value={value}>{value === "simulation-only" && chinese ? "仅仿真" : CONTROL_INTERFACE_LABELS[value]}</option>)}</select></label>
            <label><span>{chinese ? "机载计算" : "Onboard compute"}</span><div className="autonomy-custom-select-control"><select value={computePlatformIsCustom ? CUSTOM_COMPUTE_OPTION : form.computePlatform} onChange={(event) => updateAircraft({ computePlatform: event.target.value === CUSTOM_COMPUTE_OPTION ? "" : event.target.value })}>{COMPUTE_PLATFORMS.map((value) => <option key={value} value={value}>{value}</option>)}<option value={CUSTOM_COMPUTE_OPTION}>{chinese ? "自定义平台…" : "Custom platform…"}</option></select>{computePlatformIsCustom ? <input value={form.computePlatform.trim().toLowerCase() === "custom" ? "" : form.computePlatform} maxLength={120} placeholder={chinese ? "板卡型号与硬件修订" : "Board model and hardware revision"} aria-label={chinese ? "自定义机载计算平台" : "Custom onboard-compute platform"} onChange={(event) => updateAircraft({ computePlatform: event.target.value })} /> : null}</div></label>
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
              ["maximumPickupPayloadKg", chinese ? "最大拾取载荷 (kg)" : "Pickup capacity (kg)"],
              ["maximumSpeedMps", chinese ? "最大速度 (m/s)" : "Maximum speed (m/s)"],
              ["maximumAccelerationMps2", chinese ? "最大加速度 (m/s²)" : "Maximum acceleration (m/s²)"],
              ["maximumClimbMps", chinese ? "最大爬升 (m/s)" : "Maximum climb (m/s)"],
              ["maximumDescentMps", chinese ? "最大下降 (m/s)" : "Maximum descent (m/s)"],
              ["maximumTiltDeg", chinese ? "最大倾角 (°)" : "Maximum tilt (°)"],
            ] as Array<[keyof typeof AUTONOMY_AIRCRAFT_LIMITS, string]>).map(([key, label]) => (
              <label key={key}><span>{label}</span><input type="number" min={AUTONOMY_AIRCRAFT_LIMITS[key].min} max={AUTONOMY_AIRCRAFT_LIMITS[key].max} step="0.01" value={String(form[key])} aria-invalid={typeof form[key] !== "number" || form[key] < AUTONOMY_AIRCRAFT_LIMITS[key].min || form[key] > AUTONOMY_AIRCRAFT_LIMITS[key].max} onChange={(event) => numberField(key, event.target.value)} /></label>
            ))}
            <label><span>{chinese ? "返航保留电量 (%)" : "Reserve battery (%)"}</span><input type="number" min="10" max="90" step="1" value={form.reserveBatteryPercent} aria-invalid={form.reserveBatteryPercent < AUTONOMY_AIRCRAFT_LIMITS.reserveBatteryPercent.min || form.reserveBatteryPercent > AUTONOMY_AIRCRAFT_LIMITS.reserveBatteryPercent.max} onChange={(event) => numberField("reserveBatteryPercent", event.target.value)} /></label>
          </div>
        </section>

        <section className="autonomy-config-card">
          <header><Orbit aria-hidden="true" /><h2>{chinese ? "重心、惯量与链路" : "Dynamics & command link"}</h2></header>
          <div className="autonomy-form-grid is-four">
            {(["x", "y", "z"] as const).map((axis) => <label key={`cog-${axis}`}><span>CG {axis.toUpperCase()} (m)</span><input type="number" step="0.001" value={form.centerOfGravityM[axis]} onChange={(event) => updateAircraft({ centerOfGravityM: { ...form.centerOfGravityM, [axis]: Number(event.target.value) } })} /></label>)}
            {(["x", "y", "z"] as const).map((axis) => <label key={`inertia-${axis}`}><span>Inertia {axis.toUpperCase()} (kg·m²)</span><input type="number" min="0.000001" step="0.001" value={form.inertiaKgM2[axis]} onChange={(event) => updateAircraft({ inertiaKgM2: { ...form.inertiaKgM2, [axis]: Number(event.target.value) } })} /></label>)}
            <label><span>{chinese ? "链路类型" : "Link type"}</span><select value={form.commandLink.kind} onChange={(event) => updateAircraft({ commandLink: { ...form.commandLink, kind: event.target.value as AutonomyAircraftProfile["commandLink"]["kind"] } })}><option value="wifi">Wi-Fi</option><option value="radio">Radio</option><option value="lte-5g">LTE / 5G</option><option value="ethernet">Ethernet</option><option value="simulation">Simulation</option></select></label>
            <label><span>{chinese ? "链路延迟 (ms)" : "Link latency (ms)"}</span><input type="number" min="0" step="1" value={form.commandLink.latencyMs} onChange={(event) => updateAircraft({ commandLink: { ...form.commandLink, latencyMs: Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "带宽 (Mbps)" : "Bandwidth (Mbps)"}</span><input type="number" min="0.01" step="0.1" value={form.commandLink.bandwidthMbps} onChange={(event) => updateAircraft({ commandLink: { ...form.commandLink, bandwidthMbps: Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "失联策略" : "Loss action"}</span><select value={form.commandLink.lossAction} onChange={(event) => updateAircraft({ commandLink: { ...form.commandLink, lossAction: event.target.value as AutonomyAircraftProfile["commandLink"]["lossAction"] } })}><option value="hold-land">HOLD → LAND</option><option value="return-land">RETURN → LAND</option><option value="land">LAND</option></select></label>
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
          <div className="autonomy-sensor-mounts">
            {form.sensorMounts.map((sensor) => <article key={sensor.id}>
              <header><strong>{SENSOR_LABELS[sensor.kind]}</strong><label className="autonomy-calibration-state" data-state={sensor.calibrationStatus}><span>{chinese ? "标定状态" : "Calibration"}</span><select value={sensor.calibrationStatus} onChange={(event) => {
                const calibrationStatus = event.target.value as AutonomyAircraftProfile["sensorMounts"][number]["calibrationStatus"];
                updateSensorMount(sensor.id, { calibrationStatus, calibrated: calibrationStatus === "verified" });
              }}><option value="unverified">{chinese ? "未标定" : "Not calibrated"}</option><option value="verified">{chinese ? "已验证" : "Verified"}</option><option value="expired">{chinese ? "已过期" : "Expired"}</option><option value="failed">{chinese ? "验证失败" : "Failed"}</option></select></label></header>
              <label className="is-id"><span>{chinese ? "挂载 ID" : "Mount ID"}</span><input value={sensor.id} maxLength={80} onChange={(event) => updateSensorMount(sensor.id, { id: event.target.value })} /></label>
              <div>
                {(["x", "y", "z"] as const).map((axis) => <label key={`position-${axis}`}><span>{axis.toUpperCase()} (m)</span><input type="number" step="0.001" value={sensor.positionM[axis]} onChange={(event) => updateSensorMount(sensor.id, { positionM: { ...sensor.positionM, [axis]: Number(event.target.value) } })} /></label>)}
                {(["x", "y", "z"] as const).map((axis, index) => <label key={`rotation-${axis}`}><span>{["Roll", "Pitch", "Yaw"][index]} (°)</span><input type="number" step="0.1" value={sensor.rollPitchYawDeg[axis]} onChange={(event) => updateSensorMount(sensor.id, { rollPitchYawDeg: { ...sensor.rollPitchYawDeg, [axis]: Number(event.target.value) } })} /></label>)}
                <label><span>Rate (Hz)</span><input type="number" min="0.1" max="1000" step="1" value={sensor.rateHz} onChange={(event) => updateSensorMount(sensor.id, { rateHz: Number(event.target.value) })} /></label>
                <label><span>{chinese ? "标定年龄 (天)" : "Calibration age (d)"}</span><input type="number" min="0" max="3650" step="1" value={sensor.calibrationAgeDays} onChange={(event) => updateSensorMount(sensor.id, { calibrationAgeDays: Number(event.target.value) })} /></label>
              </div>
            </article>)}
          </div>
        </section>
      </div>

      <aside className="autonomy-config-summary">
        <header><Gauge aria-hidden="true" /><h2>{chinese ? "飞行包络" : "Flight envelope"}</h2></header>
        <div className="autonomy-config-summary-metrics">
          <Metric icon={<Weight aria-hidden="true" />} label={chinese ? "可用载荷" : "Payload margin"} value={`${payloadMargin.toFixed(2)} kg`} />
          <Metric icon={<Activity aria-hidden="true" />} label={chinese ? "满载推重比" : "Loaded thrust / weight"} value={thrustToWeight.toFixed(2)} />
          <Metric icon={<ScanLine aria-hidden="true" />} label={chinese ? "规划半径" : "Planning radius"} value={`${autonomyAircraftRadiusM(form).toFixed(2)} m`} />
          <Metric icon={<Camera aria-hidden="true" />} label={chinese ? "感知设备" : "Perception devices"} value={String(form.sensors.length)} />
          <Metric icon={<FileClock aria-hidden="true" />} label={chinese ? "Vehicle Pack 版本" : "Vehicle Pack version"} value={`v${form.version}`} />
          <Metric icon={<ShieldCheck aria-hidden="true" />} label={chinese ? "资格状态" : "Qualification"} value={form.status.toUpperCase()} />
        </div>
        <div className="autonomy-config-summary-actions">
          <button className="btn btn-primary" type="submit" disabled={!valid || form.status !== "draft"} title={validationIssue ?? undefined}><Save aria-hidden="true" />{validationIssue ?? (form.status !== "draft" ? (chinese ? "已验证" : "Qualified") : saved ? (chinese ? "已保存" : "Saved") : (chinese ? "保存机型" : "Save aircraft"))}</button>
          <button className="btn" type="button" disabled={!valid || !saved || qualificationState === "working" || (publicDemoConsole && qualificationState === "unavailable")} title={publicDemoConsole && qualificationState === "unavailable" ? (chinese ? "请在桌面端或私有控制台签发资格凭据" : "Qualify in the desktop or private console") : qualificationState === "blocked" ? qualificationIssues.join(" · ") || undefined : undefined} onClick={() => void qualify()}><ShieldCheck aria-hidden="true" />{qualificationState === "working" ? (chinese ? "正在验证" : "Qualifying") : qualificationState === "blocked" && qualificationIssues.length ? qualificationIssues[0] : qualificationState === "unavailable" && publicDemoConsole ? (chinese ? "请使用桌面端验证" : "Use desktop to qualify") : qualificationState === "unavailable" ? (chinese ? "重新连接后端" : "Retry backend") : (chinese ? "验证 Vehicle Pack" : "Qualify Vehicle Pack")}</button>
          {edition === "universal" ? <Link className="btn" to="/vehicle-studio"><Wrench aria-hidden="true" />Vehicle Studio</Link> : null}
        </div>
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
  "launch-zones": "Launch zones",
  rooms: "Rooms",
  corridors: "Corridors",
  roads: "Roads",
  vegetation: "Vegetation",
  "street-furniture": "Street furniture",
};

const PLANNING_LAYER_LABELS: Record<AutonomyMapPack["planningLayers"][number], string> = {
  "collision-geometry": "Collision geometry",
  occupancy: "Occupancy",
  esdf: "3D ESDF",
  "dynamic-overlay": "Dynamic overlay",
  confidence: "Confidence",
};

const FALLBACK_MAP_SCENE_MANIFESTS: Partial<Record<
  NonNullable<AutonomyMapPack["compilerSceneId"]>,
  AutonomyBundledMapManifest
>> = {
  "school-campus-v1": {
    schema_version: "dronedream.autonomy.bundled-map-manifest.v1",
    compiler_scene_id: "school-campus-v1",
    name: "School Map",
    representation: "hybrid-3d",
    coordinate_frame: "ENU",
    resolution_m: 0.05,
    bounds_m: { x: 120, y: 90, z: 12.6 },
    floor_count: 3,
    confidence_percent: 100,
    semantic_layers: [
      "free-space", "stairs", "doors", "gates", "people", "pickup-zones", "launch-zones",
      "rooms", "corridors", "roads", "vegetation", "street-furniture",
    ],
    planning_layers: ["collision-geometry", "occupancy", "esdf", "dynamic-overlay", "confidence"],
    manifest_sha256: "43e646efd02ea3021f2f34f00c76786e8b1aa716aa78cc3810b51341e2cbc8ec",
  },
};

function autonomyMapPackQualified(mapPack: AutonomyMapPack): boolean {
  return mapPack.status === "qualified"
    && Boolean(mapPack.compilerSceneId)
    && Boolean(mapPack.contentHash)
    && Boolean(mapPack.qualificationReceiptId)
    && mapPack.calibrated;
}

async function fileSha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function AutonomyMaps() {
  const { chinese, workspace, assetLibrary, selectMap, persist } = useAutonomyWorkspace();
  const [form, setForm] = useState(workspace.mapPack);
  const [saved, setSaved] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [qualificationState, setQualificationState] = useState<"idle" | "working" | "qualified" | "blocked" | "unavailable">("idle");
  const [qualificationIssues, setQualificationIssues] = useState<string[]>([]);
  const qualificationReceiptRef = useRef<string | null>(null);
  const [sceneManifests, setSceneManifests] = useState(FALLBACK_MAP_SCENE_MANIFESTS);
  useEffect(() => {
    setForm(workspace.mapPack);
    setSaved(true);
    const preservesCurrentReceipt = Boolean(workspace.mapPack.qualificationReceiptId)
      && workspace.mapPack.qualificationReceiptId === qualificationReceiptRef.current;
    if (autonomyMapPackQualified(workspace.mapPack)) {
      setQualificationState("qualified");
      setQualificationIssues([]);
    } else if (!preservesCurrentReceipt) {
      setQualificationState("idle");
      setQualificationIssues([]);
    }
  }, [workspace.mapPack]);
  useEffect(() => {
    if (publicDemoConsole) return;
    let active = true;
    void apiClient.listAutonomyScenes().then((catalog) => {
      if (!active) return;
      const next = { ...FALLBACK_MAP_SCENE_MANIFESTS };
      for (const item of catalog.items) {
        if (Object.hasOwn(next, item.id)) {
          next[item.id as keyof typeof next] = item.map_pack_manifest;
        }
      }
      setSceneManifests(next);
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  const ready = autonomyMapPackQualified(form);
  const createMap = () => {
    const updatedAt = new Date().toISOString();
    const next: AutonomyMapPack = {
      ...defaultAutonomyWorkspace().mapPack,
      id: `map-${crypto.randomUUID()}`,
      name: chinese ? `新地图 ${assetLibrary.maps.length + 1}` : `New map ${assetLibrary.maps.length + 1}`,
      updatedAt,
    };
    persist(updatedWorkspace(workspace, {
      mapPack: next,
      mission: {
        ...workspace.mission,
        mapPackId: next.id,
        compiledPlan: null,
        updatedAt,
      },
    }));
    setSaved(false);
  };
  const addFiles = async (files: FileList | null) => {
    if (!files) return;
    setIngesting(true);
    const importedAt = new Date().toISOString();
    try {
      const incoming = await Promise.all([...files].slice(0, 24).map(async (file): Promise<AutonomyMapSourceFile> => {
        const format = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "unknown";
        if (file.size > 25 * 1024 * 1024) {
          return { name: file.name, bytes: file.size, format, importedAt, sha256: null, receiptId: null, admission: "rejected", parser: null, layers: [] };
        }
        const sha256 = await fileSha256(file);
        if (publicDemoConsole) {
          return { name: file.name, bytes: file.size, format, importedAt, sha256, receiptId: null, admission: "local-only", parser: null, layers: [] };
        }
        try {
          const receipt = await apiClient.admitAutonomyMapAsset(file);
          return {
            name: receipt.filename,
            bytes: receipt.byte_size,
            format: receipt.format,
            importedAt: receipt.created_at,
            sha256: receipt.content_sha256,
            receiptId: receipt.receipt_id,
            admission: receipt.status,
            parser: receipt.parser,
            layers: receipt.layers,
          };
        } catch {
          return { name: file.name, bytes: file.size, format, importedAt, sha256, receiptId: null, admission: "rejected", parser: null, layers: [] };
        }
      }));
      setForm((current) => ({
        ...current,
        status: incoming.every((file) => file.admission === "admitted") ? "assets-admitted" : "draft",
        contentHash: null,
        qualificationReceiptId: null,
        calibrated: false,
        compilerSceneId: null,
        sourceFiles: [...current.sourceFiles, ...incoming].slice(0, 24),
      }));
      setSaved(false);
      setQualificationState("idle");
      setQualificationIssues([]);
    } finally {
      setIngesting(false);
    }
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    const next = {
      ...form,
      version: 1,
      status: ready
        ? "qualified" as const
        : form.sourceFiles.length && form.sourceFiles.every((file) => file.admission === "admitted")
          ? "assets-admitted" as const
          : "draft" as const,
      updatedAt: new Date().toISOString(),
    };
    persist(updatedWorkspace(workspace, {
      mapPack: next,
      mission: { ...workspace.mission, mapPackId: next.id, updatedAt: next.updatedAt },
    }));
    setForm(next);
    setSaved(true);
  };
  const toggleSemantic = (layer: AutonomyMapPack["semanticLayers"][number]) => {
    setForm((current) => ({
      ...current,
      status: "draft",
      contentHash: null,
      qualificationReceiptId: null,
      calibrated: false,
      compilerSceneId: null,
      semanticLayers: current.semanticLayers.includes(layer)
        ? current.semanticLayers.filter((item) => item !== layer)
        : [...current.semanticLayers, layer],
    }));
    setSaved(false);
    setQualificationState("idle");
  };
  const togglePlanningLayer = (layer: AutonomyMapPack["planningLayers"][number]) => {
    setForm((current) => ({
      ...current,
      calibrated: false,
      compilerSceneId: null,
      status: "draft",
      contentHash: null,
      qualificationReceiptId: null,
      planningLayers: current.planningLayers.includes(layer)
        ? current.planningLayers.filter((item) => item !== layer)
        : [...current.planningLayers, layer],
    }));
    setSaved(false);
    setQualificationState("idle");
  };
  const updateMap = (patch: Partial<AutonomyMapPack>) => {
    setForm((current) => ({
      ...current,
      ...patch,
      status: "draft",
      contentHash: null,
      qualificationReceiptId: null,
    }));
    setSaved(false);
    setQualificationState("idle");
  };
  const selectCompilerScene = (value: string) => {
    const compilerSceneId = value ? value as NonNullable<AutonomyMapPack["compilerSceneId"]> : null;
    const manifest = compilerSceneId ? sceneManifests[compilerSceneId] : null;
    setForm((current) => ({
      ...current,
      name: manifest?.name ?? current.name,
      status: "draft",
      contentHash: null,
      qualificationReceiptId: null,
      calibrated: false,
      compilerSceneId,
      representation: manifest?.representation ?? current.representation,
      coordinateFrame: manifest?.coordinate_frame ?? current.coordinateFrame,
      resolutionM: manifest?.resolution_m ?? current.resolutionM,
      floorCount: manifest?.floor_count ?? current.floorCount,
      boundsM: manifest?.bounds_m ?? current.boundsM,
      confidencePercent: manifest?.confidence_percent ?? current.confidencePercent,
      semanticLayers: manifest?.semantic_layers ?? current.semanticLayers,
      planningLayers: manifest?.planning_layers ?? current.planningLayers,
    }));
    setSaved(false);
    setQualificationState("idle");
  };
  const updateGeometry = (
    patch: Partial<Pick<AutonomyMapPack, "representation" | "coordinateFrame" | "resolutionM" | "floorCount" | "origin" | "boundsM" | "confidencePercent">>,
  ) => {
    setForm((current) => ({
      ...current,
      ...patch,
      status: "draft",
      contentHash: null,
      qualificationReceiptId: null,
      calibrated: false,
      compilerSceneId: null,
    }));
    setSaved(false);
    setQualificationState("idle");
  };
  const qualify = async () => {
    if (!form.compilerSceneId || !form.calibrated || form.sourceFiles.length > 0 || !saved) {
      setQualificationState("blocked");
      return;
    }
    if (publicDemoConsole) {
      setQualificationState("unavailable");
      return;
    }
    setQualificationState("working");
    try {
      const receipt = await apiClient.qualifyAutonomyMapPack(
        mapQualificationRequest(form),
      );
      const next: AutonomyMapPack = {
        ...form,
        status: receipt.status === "qualified" ? "qualified" : "draft",
        contentHash: receipt.status === "qualified" ? receipt.content_sha256 : null,
        qualificationReceiptId: receipt.receipt_id,
        updatedAt: receipt.created_at,
      };
      qualificationReceiptRef.current = receipt.receipt_id;
      setForm(next);
      persist(updatedWorkspace(workspace, {
        mapPack: next,
        mission: { ...workspace.mission, mapPackId: next.id, compiledPlan: null, updatedAt: next.updatedAt },
      }));
      setQualificationState(receipt.status === "qualified" ? "qualified" : "blocked");
      setQualificationIssues(receipt.issues.map((issue) => issue.message));
    } catch {
      setQualificationIssues([]);
      setQualificationState("unavailable");
    }
  };
  return (
    <form className="autonomy-config-page autonomy-maps-page" onSubmit={save}>
      <div className="autonomy-config-main">
        <section className="autonomy-config-card">
          <header><Layers3 aria-hidden="true" /><h2>{chinese ? "Map Pack" : "Map Pack"}</h2><div className="autonomy-asset-toolbar"><select aria-label={chinese ? "已保存地图" : "Saved maps"} value={workspace.mapPack.id} onChange={(event) => selectMap(event.target.value)}>{assetLibrary.maps.map((mapPack) => <option value={mapPack.id} key={mapPack.id}>{mapPack.name}</option>)}</select><button className="btn" type="button" onClick={createMap}><Plus aria-hidden="true" />{chinese ? "新建" : "New"}</button></div><em className={ready ? "is-ready" : ""}>{ready ? "READY" : "UNQUALIFIED"}</em></header>
          <div className="autonomy-form-grid is-four">
            <label className="is-wide"><span>{chinese ? "地图名称" : "Map name"}</span><input readOnly={form.compilerSceneId === "school-campus-v1"} value={form.name} maxLength={120} onChange={(event) => updateMap({ name: event.target.value })} /></label>
            <label><span>{chinese ? "三维表示" : "3D representation"}</span><select value={form.representation} onChange={(event) => updateGeometry({ representation: event.target.value as AutonomyMapPack["representation"] })}><option value="hybrid-3d">Hybrid 3D</option><option value="mesh">Mesh</option><option value="point-cloud">Point cloud</option><option value="occupancy">Occupancy / ESDF</option><option value="terrain">Terrain / DEM</option></select></label>
            <label><span>{chinese ? "坐标系" : "Coordinate frame"}</span><select value={form.coordinateFrame} onChange={(event) => updateGeometry({ coordinateFrame: event.target.value as AutonomyMapPack["coordinateFrame"] })}><option>ENU</option><option>NED</option><option>WGS84</option><option value="building-local">Building local</option></select></label>
            <label><span>{chinese ? "分辨率 (m)" : "Resolution (m)"}</span><input type="number" min="0.005" step="0.005" value={form.resolutionM} onChange={(event) => updateGeometry({ resolutionM: Number(event.target.value) })} /></label>
            <label><span>{chinese ? "楼层数" : "Floors"}</span><input type="number" min="1" max="500" step="1" value={form.floorCount} onChange={(event) => updateGeometry({ floorCount: Number(event.target.value) })} /></label>
            <label><span>{chinese ? "实时更新" : "Live updates"}</span><select value={form.liveUpdates} onChange={(event) => updateMap({ liveUpdates: event.target.value as AutonomyMapPack["liveUpdates"] })}><option value="vision-slam">Vision SLAM</option><option value="depth-fusion">Depth fusion</option><option value="lidar-fusion">LiDAR fusion</option><option value="fixed">Fixed map</option></select></label>
            <label><span>{chinese ? "东西范围 (m)" : "East / west span (m)"}</span><input type="number" min="0.1" step="0.1" value={form.boundsM.x} onChange={(event) => updateGeometry({ boundsM: { ...form.boundsM, x: Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "南北范围 (m)" : "North / south span (m)"}</span><input type="number" min="0.1" step="0.1" value={form.boundsM.y} onChange={(event) => updateGeometry({ boundsM: { ...form.boundsM, y: Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "垂直范围 (m)" : "Vertical span (m)"}</span><input type="number" min="0.1" step="0.1" value={form.boundsM.z} onChange={(event) => updateGeometry({ boundsM: { ...form.boundsM, z: Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "地图可信度 (%)" : "Map confidence (%)"}</span><input type="number" min="0" max="100" step="1" value={form.confidencePercent} onChange={(event) => updateGeometry({ confidencePercent: Number(event.target.value) })} /></label>
            <label><span>{chinese ? "原点纬度" : "Origin latitude"}</span><input type="number" min="-90" max="90" step="0.000001" placeholder={chinese ? "本地坐标可留空" : "Optional for local frames"} value={form.origin.latitude ?? ""} onChange={(event) => updateGeometry({ origin: { ...form.origin, latitude: event.target.value === "" ? null : Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "原点经度" : "Origin longitude"}</span><input type="number" min="-180" max="180" step="0.000001" placeholder={chinese ? "本地坐标可留空" : "Optional for local frames"} value={form.origin.longitude ?? ""} onChange={(event) => updateGeometry({ origin: { ...form.origin, longitude: event.target.value === "" ? null : Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "原点海拔 (m)" : "Origin altitude (m)"}</span><input type="number" step="0.1" value={form.origin.altitudeM ?? ""} onChange={(event) => updateGeometry({ origin: { ...form.origin, altitudeM: event.target.value === "" ? null : Number(event.target.value) } })} /></label>
            <label className="is-wide"><span>{chinese ? "规划场景资格" : "Planning scene qualification"}</span><select disabled={form.sourceFiles.length > 0} value={form.compilerSceneId ?? ""} onChange={(event) => selectCompilerScene(event.target.value)}><option value="">{chinese ? "未获得编译场景资格" : "No compiled scene binding"}</option>{Object.entries(sceneManifests).map(([sceneId, manifest]) => <option value={sceneId} key={sceneId}>{manifest.name}</option>)}</select></label>
             <label className="autonomy-check-control"><input type="checkbox" disabled={form.sourceFiles.length > 0 || !form.compilerSceneId} checked={form.calibrated} onChange={(event) => updateMap({ calibrated: event.target.checked })} /><span>{chinese ? "确认使用内置场景的固定比例与 ENU 坐标" : "Confirm the bundled scene's fixed scale and ENU frame"}</span></label>
          </div>
        </section>

        <section className="autonomy-config-card">
          <header><Database aria-hidden="true" /><h2>{chinese ? "地图资产" : "Map assets"}</h2></header>
          <label className="autonomy-map-upload">
            <Upload aria-hidden="true" />
            <strong>{ingesting ? (chinese ? "正在哈希并检查结构" : "Hashing and inspecting") : (chinese ? "摄取三维地图资产" : "Ingest 3D map assets")}</strong>
            <span>GLB · GLTF · PCD · PLY · GeoJSON</span>
            <input type="file" multiple accept=".glb,.gltf,.pcd,.ply,.json,.geojson" onChange={(event) => void addFiles(event.target.files)} />
          </label>
          {form.sourceFiles.length ? (
            <div className="autonomy-map-assets">
              {form.sourceFiles.map((file, index) => (
               <div key={`${file.name}-${index}`} data-admission={file.admission}><HardDrive aria-hidden="true" /><span><strong>{file.name}</strong><small>{file.format.toUpperCase()} · {(file.bytes / 1_000_000).toFixed(2)} MB · {file.admission.toUpperCase()}{file.parser ? ` · ${file.parser}` : ""}</small>{file.sha256 ? <code>{file.sha256.slice(0, 20)}</code> : null}</span><button type="button" onClick={() => { setForm({ ...form, status: "draft", contentHash: null, qualificationReceiptId: null, calibrated: false, compilerSceneId: null, sourceFiles: form.sourceFiles.filter((_, itemIndex) => itemIndex !== index) }); setSaved(false); setQualificationState("idle"); }}>×</button></div>
              ))}
            </div>
          ) : null}
        </section>

        <section className="autonomy-config-card">
          <header><MapPin aria-hidden="true" /><h2>{chinese ? "语义图层" : "Semantic layers"}</h2></header>
          <div className="autonomy-choice-grid is-semantic">
            {(Object.keys(SEMANTIC_LABELS) as AutonomyMapPack["semanticLayers"][number][]).map((layer) => (
              <button type="button" key={layer} className={form.semanticLayers.includes(layer) ? "is-selected" : ""} onClick={() => toggleSemantic(layer)}><MapPin aria-hidden="true" /><span>{SEMANTIC_LABELS[layer]}</span>{form.semanticLayers.includes(layer) ? <Check aria-hidden="true" /> : null}</button>
            ))}
          </div>
          <div className="autonomy-choice-grid is-semantic autonomy-planning-layers">
            {(Object.keys(PLANNING_LAYER_LABELS) as AutonomyMapPack["planningLayers"][number][]).map((layer) => (
              <button type="button" key={layer} className={form.planningLayers.includes(layer) ? "is-selected" : ""} onClick={() => togglePlanningLayer(layer)}><Layers3 aria-hidden="true" /><span>{PLANNING_LAYER_LABELS[layer]}</span>{form.planningLayers.includes(layer) ? <Check aria-hidden="true" /> : null}</button>
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
        <Metric icon={<Database aria-hidden="true" />} label={chinese ? "资产准入" : "Asset admission"} value={form.status.toUpperCase()} />
        <Metric icon={<Gauge aria-hidden="true" />} label={chinese ? "地图可信度" : "Map confidence"} value={`${form.confidencePercent.toFixed(0)}%`} />
        <button className="btn btn-primary" type="submit" disabled={saved}><Save aria-hidden="true" />{saved ? (chinese ? "已保存" : "Saved") : (chinese ? "保存 Map Pack" : "Save Map Pack")}</button>
        <button className="btn" type="button" disabled={!saved || !form.compilerSceneId || !form.calibrated || form.sourceFiles.length > 0 || qualificationState === "working" || qualificationState === "qualified" || (publicDemoConsole && qualificationState === "unavailable")} title={publicDemoConsole && qualificationState === "unavailable" ? (chinese ? "请在桌面端或私有控制台签发资格凭据" : "Qualify in the desktop or private console") : qualificationState === "blocked" ? qualificationIssues.join(" · ") || undefined : undefined} onClick={() => void qualify()}><ShieldCheck aria-hidden="true" />{qualificationState === "working" ? (chinese ? "正在验证" : "Qualifying") : qualificationState === "qualified" ? (chinese ? "已签发资格凭据" : "Qualification issued") : qualificationState === "blocked" && qualificationIssues.length ? qualificationIssues[0] : qualificationState === "blocked" ? (chinese ? "资格验证未通过" : "Qualification blocked") : qualificationState === "unavailable" && publicDemoConsole ? (chinese ? "请使用桌面端验证" : "Use desktop to qualify") : qualificationState === "unavailable" ? (chinese ? "重新连接后端" : "Retry backend") : (chinese ? "验证 Map Pack" : "Qualify Map Pack")}</button>
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

export function AutonomyMissionRedirect() {
  return <Navigate replace to="/autonomy" />;
}

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
  const mapReady = autonomyMapPackQualified(workspace.mapPack);
  const aircraftReady = isAutonomyAircraftProfileValid(workspace.aircraft);
  const blockers = [
    ...(!aircraftReady ? [chinese ? "机型质量包络无效" : "Aircraft mass envelope is invalid"] : []),
    ...(!mapReady ? [chinese ? "Map Pack 尚未绑定经过验证的编译场景并完成校准" : "Map Pack requires a validated compiled-scene binding and calibration"] : []),
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
        {step === 0 ? <section><header><Waypoints aria-hidden="true" /><h2>{chinese ? "任务合同" : "Task contract"}</h2><Link className="btn" to="/assistant"><Sparkles aria-hidden="true" />Tuning Chat</Link></header><blockquote>{workspace.mission.intent}</blockquote><div className="autonomy-mission-model"><Cpu aria-hidden="true" /><span>{chinese ? "规划模型" : "Planning model"}</span><strong>{workspace.mission.planningModel.provider} · {workspace.mission.planningModel.model}</strong></div>{workspace.mission.planningBrief ? <p className="autonomy-planning-brief">{workspace.mission.planningBrief}</p> : null}<div className="autonomy-contract-points"><span><i>S</i>{chinese ? "起点" : "Start"}</span><ChevronRight /><span><i>1</i>{chinese ? "工作点" : "Work point"}</span><ChevronRight /><span><i>H</i>{chinese ? "返航" : "Return"}</span></div></section> : null}
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
  const { workspace, persist } = useAutonomyWorkspace();
  const recordEvidence = useCallback((record: AutonomyEvidenceRecord) => {
    const evidence = [record, ...workspace.evidence.filter((item) => item.id !== record.id)].slice(0, 50);
    persist(updatedWorkspace(workspace, { evidence }));
  }, [persist, workspace]);
  return <AutonomyLab embedded workspace={workspace} onRunCompleted={recordEvidence} />;
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
      {workspace.evidence.length ? <div className="autonomy-evidence-runs">
        {workspace.evidence.map((record) => <article key={record.id}>
          <header><FileClock aria-hidden="true" /><strong>{record.contractId}</strong><em>{record.source.toUpperCase()}</em></header>
          <p>{record.missionIntent}</p>
          <dl><div><dt>{chinese ? "无人机" : "Aircraft"}</dt><dd>{record.aircraftName} · v{record.aircraftVersion}</dd></div><div><dt>Map Pack</dt><dd>{record.mapName}</dd></div><div><dt>{chinese ? "观测" : "Observations"}</dt><dd>{record.observationCount}</dd></div><div><dt>{chinese ? "任务图" : "Task graph"}</dt><dd>r{record.taskGraphRevision}</dd></div><div><dt>{chinese ? "决策" : "Decisions"}</dt><dd>{record.decisionCount}</dd></div><div><dt>{chinese ? "跟踪实体" : "Tracked entities"}</dt><dd>{record.trackedEntityCount}</dd></div><div><dt>{chinese ? "证据链" : "Evidence chain"}</dt><dd>{record.evidenceChainHead.slice(0, 18)}</dd></div></dl>
          <time>{formatTime(record.completedAt)}</time>
        </article>)}
      </div> : <div className="autonomy-evidence-empty">
        <FileClock aria-hidden="true" />
        <h2>{chinese ? "尚无已完成的运行证据" : "No completed runtime evidence"}</h2>
        <div><span>Mission Contract</span><ChevronRight /><span>Observations</span><ChevronRight /><span>Decisions</span><ChevronRight /><span>Replay</span></div>
        <Link className="btn btn-primary" to="/autonomy/live"><Video aria-hidden="true" />{chinese ? "打开实时运行" : "Open Live Mission"}</Link>
      </div>}
    </section>
  );
}
