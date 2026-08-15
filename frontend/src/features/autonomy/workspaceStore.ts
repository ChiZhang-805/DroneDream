import type { BrandEditionId } from "../../brand/edition-brand.generated";
import type {
  AutonomyTaskGraph,
  AutonomyTaskNode,
} from "../../types/api";

export type AutonomySensorKind =
  | "rgb"
  | "depth"
  | "stereo"
  | "thermal"
  | "lidar"
  | "gps"
  | "vio";

export type MapRepresentation =
  | "hybrid-3d"
  | "mesh"
  | "point-cloud"
  | "occupancy"
  | "terrain";

export type AutonomyCompiledSceneId =
  | "stairwell-coffee-return"
  | "forest-gate-inspection"
  | "service-corridor-dock";

export interface AutonomyVector3 {
  x: number;
  y: number;
  z: number;
}

export interface AutonomySensorMount {
  id: string;
  kind: AutonomySensorKind;
  calibrated: boolean;
  calibrationStatus: "unverified" | "verified" | "expired" | "failed";
  positionM: AutonomyVector3;
  rollPitchYawDeg: AutonomyVector3;
  rateHz: number;
  calibrationAgeDays: number;
}

export interface AutonomyAircraftProfile {
  schemaVersion: 2;
  id: string;
  version: number;
  status: "draft" | "validated-unsigned" | "signed";
  qualificationReceiptId: string | null;
  name: string;
  manufacturer: string;
  airframe: string;
  flightController: string;
  autopilot: "px4" | "ardupilot" | "custom";
  firmware: string;
  controlInterface: "px4-ros2" | "mavsdk" | "mavlink" | "simulation-only";
  computePlatform: string;
  dryMassKg: number;
  maximumTakeoffMassKg: number;
  bodyLengthM: number;
  bodyWidthM: number;
  bodyHeightM: number;
  rotorRadiusM: number;
  maximumThrustN: number;
  batteryEnergyWh: number;
  reserveBatteryPercent: number;
  centerOfGravityM: AutonomyVector3;
  inertiaKgM2: AutonomyVector3;
  maximumPickupPayloadKg: number;
  maximumSpeedMps: number;
  maximumAccelerationMps2: number;
  maximumClimbMps: number;
  maximumDescentMps: number;
  maximumTiltDeg: number;
  commandLink: {
    kind: "wifi" | "radio" | "lte-5g" | "ethernet" | "simulation";
    latencyMs: number;
    bandwidthMbps: number;
    lossAction: "hold-land" | "return-land" | "land";
  };
  sensors: AutonomySensorKind[];
  sensorMounts: AutonomySensorMount[];
  updatedAt: string;
}

export const AUTONOMY_AIRCRAFT_LIMITS = {
  dryMassKg: { min: 0.101, max: 50 },
  maximumTakeoffMassKg: { min: 0.101, max: 70 },
  bodyLengthM: { min: 0.02, max: 5.95 },
  bodyWidthM: { min: 0.02, max: 5.95 },
  bodyHeightM: { min: 0.01, max: 20 },
  rotorRadiusM: { min: 0.01, max: 2.98 },
  maximumThrustN: { min: 1.001, max: 5_000 },
  batteryEnergyWh: { min: 1, max: 1_000_000 },
  reserveBatteryPercent: { min: 10, max: 90 },
  maximumPickupPayloadKg: { min: 0, max: 20 },
  maximumSpeedMps: { min: 0.2, max: 20 },
  maximumAccelerationMps2: { min: 0.2, max: 30 },
  maximumClimbMps: { min: 0.1, max: 15 },
  maximumDescentMps: { min: 0.1, max: 10 },
  maximumTiltDeg: { min: 5, max: 75 },
} as const;

export function autonomyAircraftRadiusM(aircraft: AutonomyAircraftProfile): number {
  return Math.max(
    aircraft.rotorRadiusM,
    Math.hypot(aircraft.bodyLengthM, aircraft.bodyWidthM) / 2 + aircraft.rotorRadiusM,
  );
}

export function isAutonomyAircraftProfileValid(aircraft: AutonomyAircraftProfile): boolean {
  const within = (value: number, key: keyof typeof AUTONOMY_AIRCRAFT_LIMITS) => {
    const limit = AUTONOMY_AIRCRAFT_LIMITS[key];
    return Number.isFinite(value) && value >= limit.min && value <= limit.max;
  };
  const radiusM = autonomyAircraftRadiusM(aircraft);
  return within(aircraft.dryMassKg, "dryMassKg")
    && within(aircraft.maximumTakeoffMassKg, "maximumTakeoffMassKg")
    && aircraft.maximumTakeoffMassKg > aircraft.dryMassKg
    && within(aircraft.bodyLengthM, "bodyLengthM")
    && within(aircraft.bodyWidthM, "bodyWidthM")
    && within(aircraft.bodyHeightM, "bodyHeightM")
    && within(aircraft.rotorRadiusM, "rotorRadiusM")
    && radiusM >= 0.05
    && radiusM <= 3
    && within(aircraft.maximumThrustN, "maximumThrustN")
    && within(aircraft.batteryEnergyWh, "batteryEnergyWh")
    && within(aircraft.reserveBatteryPercent, "reserveBatteryPercent")
    && within(aircraft.maximumPickupPayloadKg, "maximumPickupPayloadKg")
    && aircraft.dryMassKg + aircraft.maximumPickupPayloadKg <= aircraft.maximumTakeoffMassKg
    && within(aircraft.maximumSpeedMps, "maximumSpeedMps")
    && within(aircraft.maximumAccelerationMps2, "maximumAccelerationMps2")
    && within(aircraft.maximumClimbMps, "maximumClimbMps")
    && within(aircraft.maximumDescentMps, "maximumDescentMps")
    && within(aircraft.maximumTiltDeg, "maximumTiltDeg")
    && (aircraft.autopilot === "px4" || aircraft.controlInterface !== "px4-ros2")
    && aircraft.commandLink.latencyMs >= 0
    && aircraft.commandLink.bandwidthMbps > 0
    && aircraft.sensorMounts.some((sensor) => (
      sensor.calibrated
      && sensor.calibrationStatus === "verified"
      && (sensor.kind === "gps" || sensor.kind === "vio")
    ));
}

export interface AutonomyMapSourceFile {
  name: string;
  bytes: number;
  format: string;
  importedAt: string;
  sha256: string | null;
  receiptId: string | null;
  admission: "local-only" | "admitted" | "rejected";
  parser: string | null;
  layers: Array<"mesh" | "point-cloud" | "semantic" | "georeference">;
}

export interface AutonomyMapPack {
  schemaVersion: 2;
  id: string;
  version: number;
  status: "draft" | "assets-admitted" | "qualified";
  contentHash: string | null;
  qualificationReceiptId: string | null;
  name: string;
  representation: MapRepresentation;
  coordinateFrame: "ENU" | "NED" | "WGS84" | "building-local";
  resolutionM: number;
  floorCount: number;
  liveUpdates: "vision-slam" | "depth-fusion" | "lidar-fusion" | "fixed";
  calibrated: boolean;
  compilerSceneId: AutonomyCompiledSceneId | null;
  semanticLayers: Array<"free-space" | "stairs" | "doors" | "gates" | "people" | "pickup-zones">;
  planningLayers: Array<"collision-geometry" | "occupancy" | "esdf" | "dynamic-overlay" | "confidence">;
  origin: { latitude: number | null; longitude: number | null; altitudeM: number | null };
  boundsM: AutonomyVector3;
  confidencePercent: number;
  sourceFiles: AutonomyMapSourceFile[];
  updatedAt: string;
}

export interface AutonomyEvidenceRecord {
  schemaVersion: 2;
  id: string;
  sessionId: string;
  contractId: string;
  completedAt: string;
  executionTarget: "simulation" | "hitl" | "hardware";
  source: "backend" | "preview";
  evidenceChainHead: string;
  observationCount: number;
  missionIntent: string;
  aircraftName: string;
  mapName: string;
  aircraftVersion: number;
  mapVersion: number;
  taskGraphRevision: number;
  decisionCount: number;
  trackedEntityCount: number;
}

export interface AutonomyMissionDraft {
  schemaVersion: 2;
  id: string;
  intent: string;
  planningModel: {
    accessMode: "platform" | "byok";
    provider: string;
    model: string;
  };
  planningBrief: string;
  planningRunId: string | null;
  conversationId: string | null;
  messages: AutonomyConversationMessage[];
  aircraftProfileId: string;
  mapPackId: string;
  compiledPlan: AutonomyMissionPlanSnapshot | null;
  currentStep: number;
  updatedAt: string;
}

export interface AutonomyConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  planContractId: string | null;
}

export interface AutonomyMissionPlanSnapshot {
  schemaVersion: 1;
  source: "backend" | "local-preview";
  contractId: string;
  sceneId: string;
  sceneName: string;
  feasible: boolean;
  readiness: "simulation_ready" | "preview_only" | "denied";
  canExecute: boolean;
  perceptionMode: "map" | "vision" | "fusion";
  steps: Array<{
    order: number;
    action: string;
    label: string;
    payloadDeltaKg: number;
  }>;
  taskGraph: AutonomyTaskGraph;
  issues: Array<{
    code: string;
    severity: "info" | "warning" | "error";
    message: string;
  }>;
  metrics: {
    routeLengthM: number;
    verticalTravelM: number;
    estimatedDurationS: number;
    minimumClearanceM: number;
    launchMassKg: number;
    postPickupMassKg: number;
    postPickupThrustToWeight: number;
    brakingDistanceM: number;
  };
  immutableSafetyRules: string[];
  compiledAt: string;
}

export interface AutonomyWorkspaceState {
  schemaVersion: 2;
  aircraft: AutonomyAircraftProfile;
  mapPack: AutonomyMapPack;
  mission: AutonomyMissionDraft;
  evidence: AutonomyEvidenceRecord[];
}

const STORAGE_PREFIX = "dronedream:autonomy-workspace:v2";
const LEGACY_STORAGE_PREFIX = "dronedream:autonomy-workspace:v1";
const MAX_SOURCE_FILES = 24;
const MAX_EVIDENCE_RECORDS = 50;
const COMPILED_SCENE_SET = new Set<AutonomyCompiledSceneId>([
  "stairwell-coffee-return",
  "forest-gate-inspection",
  "service-corridor-dock",
]);
const SENSOR_SET = new Set<AutonomySensorKind>(["rgb", "depth", "stereo", "thermal", "lidar", "gps", "vio"]);
const SEMANTIC_SET = new Set<AutonomyMapPack["semanticLayers"][number]>(["free-space", "stairs", "doors", "gates", "people", "pickup-zones"]);
const PLANNING_LAYER_SET = new Set<AutonomyMapPack["planningLayers"][number]>(["collision-geometry", "occupancy", "esdf", "dynamic-overlay", "confidence"]);

function boundedNumber(value: unknown, fallback: number, minimum: number, maximum: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(maximum, Math.max(minimum, value))
    : fallback;
}

function boundedText(value: unknown, fallback: string, maximum = 120): string {
  return typeof value === "string" && value.trim()
    ? value.trim().slice(0, maximum)
    : fallback;
}

function boundedVector(
  value: unknown,
  fallback: AutonomyVector3,
  minimum: number,
  maximum: number,
): AutonomyVector3 {
  const candidate = value && typeof value === "object" ? value as Partial<AutonomyVector3> : {};
  return {
    x: boundedNumber(candidate.x, fallback.x, minimum, maximum),
    y: boundedNumber(candidate.y, fallback.y, minimum, maximum),
    z: boundedNumber(candidate.z, fallback.z, minimum, maximum),
  };
}

function boundedTextList(value: unknown, maximumItems: number, maximumLength: number): string[] {
  return Array.isArray(value)
    ? [...new Set(value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
      .map((item) => item.trim().slice(0, maximumLength)))].slice(0, maximumItems)
    : [];
}

function normalizeMissionPlan(value: unknown): AutonomyMissionPlanSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const plan = value as Partial<AutonomyMissionPlanSnapshot>;
  const graph = plan.taskGraph && typeof plan.taskGraph === "object"
    ? plan.taskGraph as Partial<AutonomyTaskGraph>
    : {};
  const rawNodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const statuses = ["pending", "ready", "active", "blocked", "completed", "failed", "skipped"] as const;
  const executors = ["language_model", "mission_executive", "perception", "global_planner", "local_planner", "payload_controller", "px4_bridge", "operator"] as const;
  const risks = ["low", "medium", "high", "critical"] as const;
  const fallbacks = ["continue", "hold", "land", "abort"] as const;
  const insertedBy = ["compiler", "runtime", "operator"] as const;
  const nodes = rawNodes.filter((node): node is AutonomyTaskNode => Boolean(
    node
    && typeof node === "object"
    && typeof node.task_id === "string"
    && typeof node.label === "string"
    && statuses.includes(node.status)
    && executors.includes(node.executor)
    && risks.includes(node.risk)
    && fallbacks.includes(node.fallback)
    && insertedBy.includes(node.inserted_by),
  )).slice(0, 128).map((node): AutonomyTaskNode => ({
    task_id: boundedText(node.task_id, "invalid-task", 96),
    label: boundedText(node.label, "Unnamed task", 200),
    status: node.status,
    depends_on: boundedTextList(node.depends_on, 16, 96),
    executor: node.executor,
    risk: node.risk,
    max_retries: Math.round(boundedNumber(node.max_retries, 0, 0, 20)),
    timeout_s: boundedNumber(node.timeout_s, 30, 0.1, 3_600),
    fallback: node.fallback,
    expected_output: boundedText(node.expected_output, "Task completion evidence", 240),
    completion_evidence: boundedTextList(node.completion_evidence, 12, 120),
    inserted_by: node.inserted_by,
  }));
  if (!nodes.length || new Set(nodes.map((node) => node.task_id)).size !== nodes.length) return null;
  const knownTaskIds = new Set(nodes.map((node) => node.task_id));
  if (nodes.some((node) => node.depends_on.some((dependency) => !knownTaskIds.has(dependency)))) return null;

  const steps = Array.isArray(plan.steps) ? plan.steps.filter((step) => Boolean(
    step
    && typeof step === "object"
    && typeof step.action === "string"
    && typeof step.label === "string",
  )).slice(0, 64).map((step, index) => ({
    order: Math.round(boundedNumber(step.order, index + 1, 1, 64)),
    action: boundedText(step.action, "task", 64),
    label: boundedText(step.label, "Unnamed mission step", 200),
    payloadDeltaKg: boundedNumber(step.payloadDeltaKg, 0, 0, 20),
  })) : [];
  const issues = Array.isArray(plan.issues) ? plan.issues.filter((issue) => Boolean(
    issue
    && typeof issue === "object"
    && typeof issue.code === "string"
    && typeof issue.message === "string"
    && ["info", "warning", "error"].includes(String(issue.severity)),
  )).slice(0, 64).map((issue) => ({
    code: boundedText(issue.code, "mission.issue", 120),
    severity: issue.severity,
    message: boundedText(issue.message, "Mission qualification issue", 300),
  })) : [];
  const metrics = plan.metrics && typeof plan.metrics === "object" ? plan.metrics : {} as AutonomyMissionPlanSnapshot["metrics"];
  const readiness = ["simulation_ready", "preview_only", "denied"].includes(String(plan.readiness))
    ? plan.readiness as AutonomyMissionPlanSnapshot["readiness"]
    : "denied";
  const perceptionMode = ["map", "vision", "fusion"].includes(String(plan.perceptionMode))
    ? plan.perceptionMode as AutonomyMissionPlanSnapshot["perceptionMode"]
    : "fusion";
  return {
    schemaVersion: 1,
    source: plan.source === "backend" ? "backend" : "local-preview",
    contractId: boundedText(plan.contractId, "mission-contract", 160),
    sceneId: boundedText(plan.sceneId, "unbound-scene", 96),
    sceneName: boundedText(plan.sceneName, "Unbound environment", 160),
    feasible: plan.feasible === true,
    readiness,
    canExecute: plan.canExecute === true && readiness === "simulation_ready",
    perceptionMode,
    steps,
    taskGraph: {
      schema_version: "dronedream.autonomy.task-graph.v1",
      revision: Math.round(boundedNumber(graph.revision, 1, 1, 1_000_000)),
      nodes,
      active_node_ids: boundedTextList(graph.active_node_ids, 16, 96).filter((taskId) => knownTaskIds.has(taskId)),
      change_reason: boundedText(graph.change_reason, "compiled", 240),
    },
    issues,
    metrics: {
      routeLengthM: boundedNumber(metrics.routeLengthM, 0, 0, 1_000_000),
      verticalTravelM: boundedNumber(metrics.verticalTravelM, 0, 0, 1_000_000),
      estimatedDurationS: boundedNumber(metrics.estimatedDurationS, 0, 0, 10_000_000),
      minimumClearanceM: boundedNumber(metrics.minimumClearanceM, 0, 0, 10_000),
      launchMassKg: boundedNumber(metrics.launchMassKg, 0, 0, 100_000),
      postPickupMassKg: boundedNumber(metrics.postPickupMassKg, 0, 0, 100_000),
      postPickupThrustToWeight: boundedNumber(metrics.postPickupThrustToWeight, 0, 0, 1_000),
      brakingDistanceM: boundedNumber(metrics.brakingDistanceM, 0, 0, 100_000),
    },
    immutableSafetyRules: boundedTextList(plan.immutableSafetyRules, 24, 320),
    compiledAt: boundedText(plan.compiledAt, new Date().toISOString(), 40),
  };
}

function key(ownerId: string, edition: BrandEditionId): string {
  return `${STORAGE_PREFIX}:${encodeURIComponent(ownerId || "local")}:${edition}`;
}

function legacyKey(ownerId: string, edition: BrandEditionId): string {
  return `${LEGACY_STORAGE_PREFIX}:${encodeURIComponent(ownerId || "local")}:${edition}`;
}

export function defaultAutonomyWorkspace(now = new Date()): AutonomyWorkspaceState {
  const updatedAt = now.toISOString();
  return {
    schemaVersion: 2,
    aircraft: {
      schemaVersion: 2,
      id: "aircraft-primary",
      version: 1,
      status: "draft",
      qualificationReceiptId: null,
      name: "Primary research quadrotor",
      manufacturer: "Custom",
      airframe: "Quad X",
      flightController: "Pixhawk 6C",
      autopilot: "px4",
      firmware: "PX4 v1.16",
      controlInterface: "px4-ros2",
      computePlatform: "Jetson Orin NX",
      dryMassKg: 1.55,
      maximumTakeoffMassKg: 2.8,
      bodyLengthM: 0.38,
      bodyWidthM: 0.38,
      bodyHeightM: 0.18,
      rotorRadiusM: 0.17,
      maximumThrustN: 39,
      batteryEnergyWh: 88.8,
      reserveBatteryPercent: 25,
      centerOfGravityM: { x: 0, y: 0, z: -0.02 },
      inertiaKgM2: { x: 0.029, y: 0.029, z: 0.052 },
      maximumPickupPayloadKg: 0.35,
      maximumSpeedMps: 4,
      maximumAccelerationMps2: 3,
      maximumClimbMps: 2,
      maximumDescentMps: 1.5,
      maximumTiltDeg: 35,
      commandLink: {
        kind: "wifi",
        latencyMs: 35,
        bandwidthMbps: 40,
        lossAction: "hold-land",
      },
      sensors: ["rgb", "depth", "gps", "vio"],
      sensorMounts: [
        { id: "front-rgb", kind: "rgb", calibrated: true, calibrationStatus: "verified", positionM: { x: 0.18, y: 0, z: -0.03 }, rollPitchYawDeg: { x: 0, y: -8, z: 0 }, rateHz: 30, calibrationAgeDays: 7 },
        { id: "front-depth", kind: "depth", calibrated: true, calibrationStatus: "verified", positionM: { x: 0.17, y: 0, z: -0.04 }, rollPitchYawDeg: { x: 0, y: -8, z: 0 }, rateHz: 30, calibrationAgeDays: 7 },
        { id: "gps-primary", kind: "gps", calibrated: true, calibrationStatus: "verified", positionM: { x: 0, y: 0, z: 0.12 }, rollPitchYawDeg: { x: 0, y: 0, z: 0 }, rateHz: 10, calibrationAgeDays: 3 },
        { id: "vio-primary", kind: "vio", calibrated: true, calibrationStatus: "verified", positionM: { x: 0.16, y: 0, z: -0.03 }, rollPitchYawDeg: { x: 0, y: -8, z: 0 }, rateHz: 30, calibrationAgeDays: 7 },
      ],
      updatedAt,
    },
    mapPack: {
      schemaVersion: 2,
      id: "map-primary",
      version: 1,
      status: "draft",
      contentHash: null,
      qualificationReceiptId: null,
      name: "Unconfigured environment",
      representation: "hybrid-3d",
      coordinateFrame: "ENU",
      resolutionM: 0.1,
      floorCount: 1,
      liveUpdates: "depth-fusion",
      calibrated: false,
      compilerSceneId: null,
      semanticLayers: ["free-space", "people"],
      planningLayers: ["collision-geometry", "occupancy", "esdf", "dynamic-overlay", "confidence"],
      origin: { latitude: null, longitude: null, altitudeM: null },
      boundsM: { x: 40, y: 30, z: 12 },
      confidencePercent: 0,
      sourceFiles: [],
      updatedAt,
    },
    mission: {
      schemaVersion: 2,
      id: "mission-draft-primary",
      intent: "Launch, reach the assigned work point, complete the task, and return safely.",
      planningModel: { accessMode: "platform", provider: "openai", model: "gpt-4.1" },
      planningBrief: "",
      planningRunId: null,
      conversationId: null,
      messages: [],
      aircraftProfileId: "aircraft-primary",
      mapPackId: "map-primary",
      compiledPlan: null,
      currentStep: 0,
      updatedAt,
    },
    evidence: [],
  };
}

export function normalizeAutonomyWorkspace(value: unknown): AutonomyWorkspaceState {
  const fallback = defaultAutonomyWorkspace();
  if (!value || typeof value !== "object") return fallback;
  const candidate = value as Partial<AutonomyWorkspaceState>;
  const aircraft = candidate.aircraft && typeof candidate.aircraft === "object"
    ? candidate.aircraft as Partial<AutonomyAircraftProfile>
    : {};
  const mapPack = candidate.mapPack && typeof candidate.mapPack === "object"
    ? candidate.mapPack as Partial<AutonomyMapPack>
    : {};
  const mission = candidate.mission && typeof candidate.mission === "object"
    ? candidate.mission as Partial<AutonomyMissionDraft>
    : {};
  const normalizedMissionPlan = normalizeMissionPlan(mission.compiledPlan);
  const representation = ["hybrid-3d", "mesh", "point-cloud", "occupancy", "terrain"].includes(String(mapPack.representation))
    ? mapPack.representation as MapRepresentation
    : fallback.mapPack.representation;
  const coordinateFrame = ["ENU", "NED", "WGS84", "building-local"].includes(String(mapPack.coordinateFrame))
    ? mapPack.coordinateFrame as AutonomyMapPack["coordinateFrame"]
    : fallback.mapPack.coordinateFrame;
  const liveUpdates = ["vision-slam", "depth-fusion", "lidar-fusion", "fixed"].includes(String(mapPack.liveUpdates))
    ? mapPack.liveUpdates as AutonomyMapPack["liveUpdates"]
    : fallback.mapPack.liveUpdates;
  const updatedAt = new Date().toISOString();
  const normalizedSourceFiles = Array.isArray(mapPack.sourceFiles)
    ? mapPack.sourceFiles.filter((file): file is AutonomyMapSourceFile => Boolean(
      file && typeof file === "object" && typeof file.name === "string" && typeof file.bytes === "number",
    )).slice(0, MAX_SOURCE_FILES).map((file): AutonomyMapSourceFile => ({
      name: boundedText(file.name, "map-asset", 255),
      bytes: Math.round(boundedNumber(file.bytes, 0, 0, 2_000_000_000)),
      format: boundedText(file.format, "unknown", 32),
      importedAt: boundedText(file.importedAt, updatedAt, 40),
      sha256: typeof file.sha256 === "string" ? file.sha256.slice(0, 64) : null,
      receiptId: typeof file.receiptId === "string" ? file.receiptId.slice(0, 120) : null,
      admission: file.admission === "admitted" || file.admission === "rejected" ? file.admission : "local-only",
      parser: typeof file.parser === "string" ? file.parser.slice(0, 80) : null,
      layers: Array.isArray(file.layers)
        ? [...new Set(file.layers.filter((layer): layer is AutonomyMapSourceFile["layers"][number] => ["mesh", "point-cloud", "semantic", "georeference"].includes(String(layer))))]
        : [],
    }))
    : [];
  const importedMapAwaitingIngestion = normalizedSourceFiles.length > 0;
  const normalizedSensors = Array.isArray(aircraft.sensors)
    ? [...new Set(aircraft.sensors.filter((sensor): sensor is AutonomySensorKind => SENSOR_SET.has(sensor as AutonomySensorKind)))].slice(0, SENSOR_SET.size)
    : fallback.aircraft.sensors;
  const sensorCalibrationContractMigrated = Array.isArray(aircraft.sensorMounts) && aircraft.sensorMounts.some((sensor) => (
    !sensor
    || typeof sensor !== "object"
    || !["unverified", "verified", "expired", "failed"].includes(String(sensor.calibrationStatus))
  ));
  const normalizedSensorMounts = Array.isArray(aircraft.sensorMounts)
    ? aircraft.sensorMounts.filter((sensor): sensor is AutonomySensorMount => Boolean(
      sensor && typeof sensor === "object" && SENSOR_SET.has(sensor.kind as AutonomySensorKind),
    )).slice(0, 64).map((sensor, index) => ({
      id: boundedText(sensor.id, `sensor-${index + 1}`, 80),
      kind: sensor.kind,
      calibrated: sensor.calibrationStatus
        ? sensor.calibrationStatus === "verified"
        : sensor.calibrated === true,
      calibrationStatus: ["unverified", "verified", "expired", "failed"].includes(String(sensor.calibrationStatus))
        ? sensor.calibrationStatus
        : sensor.calibrated === true ? "verified" : "unverified",
      positionM: boundedVector(sensor.positionM, { x: 0, y: 0, z: 0 }, -10, 10),
      rollPitchYawDeg: boundedVector(sensor.rollPitchYawDeg, { x: 0, y: 0, z: 0 }, -360, 360),
      rateHz: boundedNumber(sensor.rateHz, 30, 0.1, 1_000),
      calibrationAgeDays: boundedNumber(sensor.calibrationAgeDays, 0, 0, 3_650),
    }))
    : fallback.aircraft.sensorMounts.filter((sensor) => normalizedSensors.includes(sensor.kind));
  const commandLink = aircraft.commandLink && typeof aircraft.commandLink === "object"
    ? aircraft.commandLink
    : fallback.aircraft.commandLink;
  const autopilotWasInferred = !["px4", "ardupilot", "custom"].includes(String(aircraft.autopilot));
  const normalizedAutopilot = !autopilotWasInferred
    ? aircraft.autopilot as AutonomyAircraftProfile["autopilot"]
    : typeof aircraft.firmware === "string" && aircraft.firmware.toLowerCase().includes("ardu") ? "ardupilot" : "px4";
  const requestedControlInterface = ["px4-ros2", "mavsdk", "mavlink", "simulation-only"].includes(String(aircraft.controlInterface))
    ? aircraft.controlInterface as AutonomyAircraftProfile["controlInterface"]
    : fallback.aircraft.controlInterface;
  const normalizedControlInterface = normalizedAutopilot !== "px4" && requestedControlInterface === "px4-ros2"
    ? "mavlink"
    : requestedControlInterface;
  const qualificationContractMigrated = autopilotWasInferred
    || normalizedControlInterface !== requestedControlInterface
    || sensorCalibrationContractMigrated;
  const normalizedAircraft: AutonomyAircraftProfile = {
    ...fallback.aircraft,
    schemaVersion: 2,
    id: boundedText(aircraft.id, fallback.aircraft.id, 80),
    version: Math.round(boundedNumber(aircraft.version, fallback.aircraft.version, 1, 1_000_000)),
    status: qualificationContractMigrated
      ? "draft"
      : aircraft.status === "validated-unsigned" || aircraft.status === "signed" ? aircraft.status : "draft",
    qualificationReceiptId: !qualificationContractMigrated && typeof aircraft.qualificationReceiptId === "string"
      ? aircraft.qualificationReceiptId.slice(0, 160)
      : null,
    name: boundedText(aircraft.name, fallback.aircraft.name),
    manufacturer: boundedText(aircraft.manufacturer, fallback.aircraft.manufacturer),
    airframe: boundedText(aircraft.airframe, fallback.aircraft.airframe),
    flightController: boundedText(aircraft.flightController, fallback.aircraft.flightController),
    autopilot: normalizedAutopilot,
    firmware: boundedText(aircraft.firmware, fallback.aircraft.firmware),
    controlInterface: normalizedControlInterface,
    computePlatform: boundedText(aircraft.computePlatform, fallback.aircraft.computePlatform),
    dryMassKg: boundedNumber(aircraft.dryMassKg, fallback.aircraft.dryMassKg, AUTONOMY_AIRCRAFT_LIMITS.dryMassKg.min, AUTONOMY_AIRCRAFT_LIMITS.dryMassKg.max),
    maximumTakeoffMassKg: boundedNumber(aircraft.maximumTakeoffMassKg, fallback.aircraft.maximumTakeoffMassKg, AUTONOMY_AIRCRAFT_LIMITS.maximumTakeoffMassKg.min, AUTONOMY_AIRCRAFT_LIMITS.maximumTakeoffMassKg.max),
    bodyLengthM: boundedNumber(aircraft.bodyLengthM, fallback.aircraft.bodyLengthM, AUTONOMY_AIRCRAFT_LIMITS.bodyLengthM.min, AUTONOMY_AIRCRAFT_LIMITS.bodyLengthM.max),
    bodyWidthM: boundedNumber(aircraft.bodyWidthM, fallback.aircraft.bodyWidthM, AUTONOMY_AIRCRAFT_LIMITS.bodyWidthM.min, AUTONOMY_AIRCRAFT_LIMITS.bodyWidthM.max),
    bodyHeightM: boundedNumber(aircraft.bodyHeightM, fallback.aircraft.bodyHeightM, AUTONOMY_AIRCRAFT_LIMITS.bodyHeightM.min, AUTONOMY_AIRCRAFT_LIMITS.bodyHeightM.max),
    rotorRadiusM: boundedNumber(aircraft.rotorRadiusM, fallback.aircraft.rotorRadiusM, AUTONOMY_AIRCRAFT_LIMITS.rotorRadiusM.min, AUTONOMY_AIRCRAFT_LIMITS.rotorRadiusM.max),
    maximumThrustN: boundedNumber(aircraft.maximumThrustN, fallback.aircraft.maximumThrustN, AUTONOMY_AIRCRAFT_LIMITS.maximumThrustN.min, AUTONOMY_AIRCRAFT_LIMITS.maximumThrustN.max),
    batteryEnergyWh: boundedNumber(aircraft.batteryEnergyWh, fallback.aircraft.batteryEnergyWh, AUTONOMY_AIRCRAFT_LIMITS.batteryEnergyWh.min, AUTONOMY_AIRCRAFT_LIMITS.batteryEnergyWh.max),
    reserveBatteryPercent: boundedNumber(aircraft.reserveBatteryPercent, fallback.aircraft.reserveBatteryPercent, AUTONOMY_AIRCRAFT_LIMITS.reserveBatteryPercent.min, AUTONOMY_AIRCRAFT_LIMITS.reserveBatteryPercent.max),
    centerOfGravityM: boundedVector(aircraft.centerOfGravityM, fallback.aircraft.centerOfGravityM, -10, 10),
    inertiaKgM2: boundedVector(aircraft.inertiaKgM2, fallback.aircraft.inertiaKgM2, 0.000001, 10_000),
    maximumPickupPayloadKg: boundedNumber(aircraft.maximumPickupPayloadKg, fallback.aircraft.maximumPickupPayloadKg, AUTONOMY_AIRCRAFT_LIMITS.maximumPickupPayloadKg.min, AUTONOMY_AIRCRAFT_LIMITS.maximumPickupPayloadKg.max),
    maximumSpeedMps: boundedNumber(aircraft.maximumSpeedMps, fallback.aircraft.maximumSpeedMps, AUTONOMY_AIRCRAFT_LIMITS.maximumSpeedMps.min, AUTONOMY_AIRCRAFT_LIMITS.maximumSpeedMps.max),
    maximumAccelerationMps2: boundedNumber(aircraft.maximumAccelerationMps2, fallback.aircraft.maximumAccelerationMps2, AUTONOMY_AIRCRAFT_LIMITS.maximumAccelerationMps2.min, AUTONOMY_AIRCRAFT_LIMITS.maximumAccelerationMps2.max),
    maximumClimbMps: boundedNumber(aircraft.maximumClimbMps, fallback.aircraft.maximumClimbMps, AUTONOMY_AIRCRAFT_LIMITS.maximumClimbMps.min, AUTONOMY_AIRCRAFT_LIMITS.maximumClimbMps.max),
    maximumDescentMps: boundedNumber(aircraft.maximumDescentMps, fallback.aircraft.maximumDescentMps, AUTONOMY_AIRCRAFT_LIMITS.maximumDescentMps.min, AUTONOMY_AIRCRAFT_LIMITS.maximumDescentMps.max),
    maximumTiltDeg: boundedNumber(aircraft.maximumTiltDeg, fallback.aircraft.maximumTiltDeg, AUTONOMY_AIRCRAFT_LIMITS.maximumTiltDeg.min, AUTONOMY_AIRCRAFT_LIMITS.maximumTiltDeg.max),
    commandLink: {
      kind: ["wifi", "radio", "lte-5g", "ethernet", "simulation"].includes(String(commandLink.kind)) ? commandLink.kind : fallback.aircraft.commandLink.kind,
      latencyMs: boundedNumber(commandLink.latencyMs, fallback.aircraft.commandLink.latencyMs, 0, 60_000),
      bandwidthMbps: boundedNumber(commandLink.bandwidthMbps, fallback.aircraft.commandLink.bandwidthMbps, 0.01, 100_000),
      lossAction: ["hold-land", "return-land", "land"].includes(String(commandLink.lossAction)) ? commandLink.lossAction : fallback.aircraft.commandLink.lossAction,
    },
    sensors: normalizedSensors,
    sensorMounts: normalizedSensorMounts,
    updatedAt: boundedText(aircraft.updatedAt, updatedAt, 40),
  };
  const normalizedMap: AutonomyMapPack = {
    ...fallback.mapPack,
    schemaVersion: 2,
    id: boundedText(mapPack.id, fallback.mapPack.id, 80),
    version: Math.round(boundedNumber(mapPack.version, fallback.mapPack.version, 1, 1_000_000)),
    status: normalizedSourceFiles.length
      ? (normalizedSourceFiles.every((file) => file.admission === "admitted") ? "assets-admitted" : "draft")
      : (mapPack.calibrated === true && COMPILED_SCENE_SET.has(mapPack.compilerSceneId as AutonomyCompiledSceneId) ? "qualified" : "draft"),
    contentHash: typeof mapPack.contentHash === "string" ? mapPack.contentHash.slice(0, 64) : null,
    qualificationReceiptId: typeof mapPack.qualificationReceiptId === "string" ? mapPack.qualificationReceiptId.slice(0, 160) : null,
    name: boundedText(mapPack.name, fallback.mapPack.name),
    representation,
    coordinateFrame,
    resolutionM: boundedNumber(mapPack.resolutionM, fallback.mapPack.resolutionM, 0.005, 100),
    floorCount: Math.round(boundedNumber(mapPack.floorCount, fallback.mapPack.floorCount, 1, 500)),
    liveUpdates,
    calibrated: !importedMapAwaitingIngestion && mapPack.calibrated === true,
    compilerSceneId: !importedMapAwaitingIngestion && COMPILED_SCENE_SET.has(mapPack.compilerSceneId as AutonomyCompiledSceneId)
      ? mapPack.compilerSceneId as AutonomyCompiledSceneId
      : null,
    semanticLayers: Array.isArray(mapPack.semanticLayers)
      ? [...new Set(mapPack.semanticLayers.filter((layer): layer is AutonomyMapPack["semanticLayers"][number] => SEMANTIC_SET.has(layer as AutonomyMapPack["semanticLayers"][number])))].slice(0, SEMANTIC_SET.size)
      : fallback.mapPack.semanticLayers,
    planningLayers: Array.isArray(mapPack.planningLayers)
      ? [...new Set(mapPack.planningLayers.filter((layer): layer is AutonomyMapPack["planningLayers"][number] => PLANNING_LAYER_SET.has(layer as AutonomyMapPack["planningLayers"][number])))].slice(0, PLANNING_LAYER_SET.size)
      : fallback.mapPack.planningLayers,
    origin: {
      latitude: typeof mapPack.origin?.latitude === "number" && Number.isFinite(mapPack.origin.latitude) ? Math.min(90, Math.max(-90, mapPack.origin.latitude)) : null,
      longitude: typeof mapPack.origin?.longitude === "number" && Number.isFinite(mapPack.origin.longitude) ? Math.min(180, Math.max(-180, mapPack.origin.longitude)) : null,
      altitudeM: typeof mapPack.origin?.altitudeM === "number" && Number.isFinite(mapPack.origin.altitudeM) ? mapPack.origin.altitudeM : null,
    },
    boundsM: boundedVector(mapPack.boundsM, fallback.mapPack.boundsM, 0.1, 100_000),
    confidencePercent: boundedNumber(mapPack.confidencePercent, fallback.mapPack.confidencePercent, 0, 100),
    sourceFiles: normalizedSourceFiles,
    updatedAt: boundedText(mapPack.updatedAt, updatedAt, 40),
  };
  return {
    schemaVersion: 2,
    aircraft: normalizedAircraft,
    mapPack: normalizedMap,
    mission: {
      ...fallback.mission,
      id: boundedText(mission.id, fallback.mission.id, 80),
      intent: boundedText(mission.intent, fallback.mission.intent, 2_000),
      planningModel: mission.planningModel && typeof mission.planningModel === "object"
        ? {
            accessMode: mission.planningModel.accessMode === "byok" ? "byok" : "platform",
            provider: boundedText(mission.planningModel.provider, fallback.mission.planningModel.provider, 80),
            model: boundedText(mission.planningModel.model, fallback.mission.planningModel.model, 160),
          }
        : fallback.mission.planningModel,
      planningBrief: boundedText(mission.planningBrief, fallback.mission.planningBrief, 4_000),
      planningRunId: typeof mission.planningRunId === "string"
        ? boundedText(mission.planningRunId, "", 160) || null
        : null,
      conversationId: typeof mission.conversationId === "string"
        ? boundedText(mission.conversationId, "", 160) || null
        : null,
      messages: Array.isArray(mission.messages)
        ? mission.messages.filter((message): message is AutonomyConversationMessage => Boolean(
          message
          && typeof message === "object"
          && (message.role === "user" || message.role === "assistant")
          && typeof message.content === "string",
        )).slice(-100).map((message) => ({
          id: boundedText(message.id, crypto.randomUUID(), 160),
          role: message.role,
          content: boundedText(message.content, "Empty message", 6_000),
          createdAt: boundedText(message.createdAt, updatedAt, 40),
          planContractId: typeof message.planContractId === "string"
            ? boundedText(message.planContractId, "", 160) || null
            : null,
        }))
        : [],
      aircraftProfileId: normalizedAircraft.id,
      mapPackId: normalizedMap.id,
      compiledPlan: normalizedMissionPlan,
      currentStep: Math.round(boundedNumber(mission.currentStep, 0, 0, 5)),
      updatedAt: boundedText(mission.updatedAt, updatedAt, 40),
    },
    evidence: Array.isArray(candidate.evidence)
      ? candidate.evidence.filter((record): record is AutonomyEvidenceRecord => Boolean(
        record
        && typeof record === "object"
        && typeof record.id === "string"
        && typeof record.sessionId === "string"
        && typeof record.contractId === "string",
      )).slice(0, MAX_EVIDENCE_RECORDS).map((record) => ({
        schemaVersion: 2,
        id: boundedText(record.id, crypto.randomUUID(), 160),
        sessionId: boundedText(record.sessionId, "unknown-session", 160),
        contractId: boundedText(record.contractId, "unknown-contract", 160),
        completedAt: boundedText(record.completedAt, updatedAt, 40),
        executionTarget: ["simulation", "hitl", "hardware"].includes(record.executionTarget)
          ? record.executionTarget
          : "simulation",
        source: record.source === "backend" ? "backend" : "preview",
        evidenceChainHead: boundedText(record.evidenceChainHead, "preview-only", 256),
        observationCount: Math.round(boundedNumber(record.observationCount, 0, 0, 1_000_000)),
        missionIntent: boundedText(record.missionIntent, fallback.mission.intent, 2_000),
        aircraftName: boundedText(record.aircraftName, normalizedAircraft.name, 120),
        mapName: boundedText(record.mapName, normalizedMap.name, 120),
        aircraftVersion: Math.round(boundedNumber(record.aircraftVersion, normalizedAircraft.version, 1, 1_000_000)),
        mapVersion: Math.round(boundedNumber(record.mapVersion, normalizedMap.version, 1, 1_000_000)),
        taskGraphRevision: Math.round(boundedNumber(record.taskGraphRevision, 1, 1, 1_000_000)),
        decisionCount: Math.round(boundedNumber(record.decisionCount, 0, 0, 1_000_000)),
        trackedEntityCount: Math.round(boundedNumber(record.trackedEntityCount, 0, 0, 1_000_000)),
      }))
      : [],
  };
}

export function loadAutonomyWorkspace(
  ownerId: string,
  edition: BrandEditionId,
  storage: Pick<Storage, "getItem"> = window.localStorage,
): AutonomyWorkspaceState {
  try {
    const current = storage.getItem(key(ownerId, edition));
    const legacy = current === null ? storage.getItem(legacyKey(ownerId, edition)) : null;
    return normalizeAutonomyWorkspace(JSON.parse(current ?? legacy ?? "null"));
  } catch {
    return defaultAutonomyWorkspace();
  }
}

export function saveAutonomyWorkspace(
  ownerId: string,
  edition: BrandEditionId,
  workspace: AutonomyWorkspaceState,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): AutonomyWorkspaceState {
  const normalized = normalizeAutonomyWorkspace(workspace);
  storage.setItem(key(ownerId, edition), JSON.stringify(normalized));
  return normalized;
}
