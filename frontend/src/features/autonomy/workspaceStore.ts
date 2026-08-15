import type { BrandEditionId } from "../../brand/edition-brand.generated";

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

export interface AutonomyAircraftProfile {
  schemaVersion: 1;
  id: string;
  name: string;
  manufacturer: string;
  airframe: string;
  firmware: string;
  dryMassKg: number;
  maximumTakeoffMassKg: number;
  bodyLengthM: number;
  bodyWidthM: number;
  bodyHeightM: number;
  rotorRadiusM: number;
  maximumThrustN: number;
  batteryEnergyWh: number;
  reserveBatteryPercent: number;
  sensors: AutonomySensorKind[];
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
    && within(aircraft.reserveBatteryPercent, "reserveBatteryPercent");
}

export interface AutonomyMapSourceFile {
  name: string;
  bytes: number;
  format: string;
  importedAt: string;
}

export interface AutonomyMapPack {
  schemaVersion: 1;
  id: string;
  name: string;
  representation: MapRepresentation;
  coordinateFrame: "ENU" | "NED" | "WGS84" | "building-local";
  resolutionM: number;
  floorCount: number;
  liveUpdates: "vision-slam" | "depth-fusion" | "lidar-fusion" | "fixed";
  calibrated: boolean;
  compilerSceneId: AutonomyCompiledSceneId | null;
  semanticLayers: Array<"free-space" | "stairs" | "doors" | "gates" | "people" | "pickup-zones">;
  sourceFiles: AutonomyMapSourceFile[];
  updatedAt: string;
}

export interface AutonomyEvidenceRecord {
  schemaVersion: 1;
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
}

export interface AutonomyMissionDraft {
  schemaVersion: 1;
  id: string;
  intent: string;
  aircraftProfileId: string;
  mapPackId: string;
  currentStep: number;
  updatedAt: string;
}

export interface AutonomyWorkspaceState {
  schemaVersion: 1;
  aircraft: AutonomyAircraftProfile;
  mapPack: AutonomyMapPack;
  mission: AutonomyMissionDraft;
  evidence: AutonomyEvidenceRecord[];
}

const STORAGE_PREFIX = "dronedream:autonomy-workspace:v1";
const MAX_SOURCE_FILES = 24;
const MAX_EVIDENCE_RECORDS = 50;
const COMPILED_SCENE_SET = new Set<AutonomyCompiledSceneId>([
  "stairwell-coffee-return",
  "forest-gate-inspection",
  "service-corridor-dock",
]);
const SENSOR_SET = new Set<AutonomySensorKind>(["rgb", "depth", "stereo", "thermal", "lidar", "gps", "vio"]);
const SEMANTIC_SET = new Set<AutonomyMapPack["semanticLayers"][number]>(["free-space", "stairs", "doors", "gates", "people", "pickup-zones"]);

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

function key(ownerId: string, edition: BrandEditionId): string {
  return `${STORAGE_PREFIX}:${encodeURIComponent(ownerId || "local")}:${edition}`;
}

export function defaultAutonomyWorkspace(now = new Date()): AutonomyWorkspaceState {
  const updatedAt = now.toISOString();
  return {
    schemaVersion: 1,
    aircraft: {
      schemaVersion: 1,
      id: "aircraft-primary",
      name: "Primary research quadrotor",
      manufacturer: "Custom",
      airframe: "Quad X",
      firmware: "PX4 v1.16",
      dryMassKg: 1.55,
      maximumTakeoffMassKg: 2.8,
      bodyLengthM: 0.38,
      bodyWidthM: 0.38,
      bodyHeightM: 0.18,
      rotorRadiusM: 0.17,
      maximumThrustN: 39,
      batteryEnergyWh: 88.8,
      reserveBatteryPercent: 25,
      sensors: ["rgb", "depth", "gps", "vio"],
      updatedAt,
    },
    mapPack: {
      schemaVersion: 1,
      id: "map-primary",
      name: "Unconfigured environment",
      representation: "hybrid-3d",
      coordinateFrame: "ENU",
      resolutionM: 0.1,
      floorCount: 1,
      liveUpdates: "depth-fusion",
      calibrated: false,
      compilerSceneId: null,
      semanticLayers: ["free-space", "people"],
      sourceFiles: [],
      updatedAt,
    },
    mission: {
      schemaVersion: 1,
      id: "mission-draft-primary",
      intent: "Launch, reach the assigned work point, complete the task, and return safely.",
      aircraftProfileId: "aircraft-primary",
      mapPackId: "map-primary",
      currentStep: 0,
      updatedAt,
    },
    evidence: [],
  };
}

function normalize(value: unknown): AutonomyWorkspaceState {
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
    )).slice(0, MAX_SOURCE_FILES).map((file) => ({
      name: boundedText(file.name, "map-asset", 255),
      bytes: Math.round(boundedNumber(file.bytes, 0, 0, 2_000_000_000)),
      format: boundedText(file.format, "unknown", 32),
      importedAt: boundedText(file.importedAt, updatedAt, 40),
    }))
    : [];
  const importedMapAwaitingIngestion = normalizedSourceFiles.length > 0;
  const normalizedAircraft: AutonomyAircraftProfile = {
    ...fallback.aircraft,
    id: boundedText(aircraft.id, fallback.aircraft.id, 80),
    name: boundedText(aircraft.name, fallback.aircraft.name),
    manufacturer: boundedText(aircraft.manufacturer, fallback.aircraft.manufacturer),
    airframe: boundedText(aircraft.airframe, fallback.aircraft.airframe),
    firmware: boundedText(aircraft.firmware, fallback.aircraft.firmware),
    dryMassKg: boundedNumber(aircraft.dryMassKg, fallback.aircraft.dryMassKg, AUTONOMY_AIRCRAFT_LIMITS.dryMassKg.min, AUTONOMY_AIRCRAFT_LIMITS.dryMassKg.max),
    maximumTakeoffMassKg: boundedNumber(aircraft.maximumTakeoffMassKg, fallback.aircraft.maximumTakeoffMassKg, AUTONOMY_AIRCRAFT_LIMITS.maximumTakeoffMassKg.min, AUTONOMY_AIRCRAFT_LIMITS.maximumTakeoffMassKg.max),
    bodyLengthM: boundedNumber(aircraft.bodyLengthM, fallback.aircraft.bodyLengthM, AUTONOMY_AIRCRAFT_LIMITS.bodyLengthM.min, AUTONOMY_AIRCRAFT_LIMITS.bodyLengthM.max),
    bodyWidthM: boundedNumber(aircraft.bodyWidthM, fallback.aircraft.bodyWidthM, AUTONOMY_AIRCRAFT_LIMITS.bodyWidthM.min, AUTONOMY_AIRCRAFT_LIMITS.bodyWidthM.max),
    bodyHeightM: boundedNumber(aircraft.bodyHeightM, fallback.aircraft.bodyHeightM, AUTONOMY_AIRCRAFT_LIMITS.bodyHeightM.min, AUTONOMY_AIRCRAFT_LIMITS.bodyHeightM.max),
    rotorRadiusM: boundedNumber(aircraft.rotorRadiusM, fallback.aircraft.rotorRadiusM, AUTONOMY_AIRCRAFT_LIMITS.rotorRadiusM.min, AUTONOMY_AIRCRAFT_LIMITS.rotorRadiusM.max),
    maximumThrustN: boundedNumber(aircraft.maximumThrustN, fallback.aircraft.maximumThrustN, AUTONOMY_AIRCRAFT_LIMITS.maximumThrustN.min, AUTONOMY_AIRCRAFT_LIMITS.maximumThrustN.max),
    batteryEnergyWh: boundedNumber(aircraft.batteryEnergyWh, fallback.aircraft.batteryEnergyWh, AUTONOMY_AIRCRAFT_LIMITS.batteryEnergyWh.min, AUTONOMY_AIRCRAFT_LIMITS.batteryEnergyWh.max),
    reserveBatteryPercent: boundedNumber(aircraft.reserveBatteryPercent, fallback.aircraft.reserveBatteryPercent, AUTONOMY_AIRCRAFT_LIMITS.reserveBatteryPercent.min, AUTONOMY_AIRCRAFT_LIMITS.reserveBatteryPercent.max),
    sensors: Array.isArray(aircraft.sensors)
      ? [...new Set(aircraft.sensors.filter((sensor): sensor is AutonomySensorKind => SENSOR_SET.has(sensor as AutonomySensorKind)))].slice(0, SENSOR_SET.size)
      : fallback.aircraft.sensors,
    updatedAt: boundedText(aircraft.updatedAt, updatedAt, 40),
  };
  const normalizedMap: AutonomyMapPack = {
    ...fallback.mapPack,
    id: boundedText(mapPack.id, fallback.mapPack.id, 80),
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
    sourceFiles: normalizedSourceFiles,
    updatedAt: boundedText(mapPack.updatedAt, updatedAt, 40),
  };
  return {
    schemaVersion: 1,
    aircraft: normalizedAircraft,
    mapPack: normalizedMap,
    mission: {
      ...fallback.mission,
      id: boundedText(mission.id, fallback.mission.id, 80),
      intent: boundedText(mission.intent, fallback.mission.intent, 2_000),
      aircraftProfileId: normalizedAircraft.id,
      mapPackId: normalizedMap.id,
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
        schemaVersion: 1,
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
    return normalize(JSON.parse(storage.getItem(key(ownerId, edition)) ?? "null"));
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
  const normalized = normalize(workspace);
  storage.setItem(key(ownerId, edition), JSON.stringify(normalized));
  return normalized;
}
