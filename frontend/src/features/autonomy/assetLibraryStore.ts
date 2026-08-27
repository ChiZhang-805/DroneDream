import type { BrandEditionId } from "../../brand/edition-brand.generated";
import {
  defaultAutonomyWorkspace,
  normalizeAutonomyWorkspace,
  type AutonomyAircraftProfile,
  type AutonomyMapPack,
  type AutonomyWorkspaceState,
} from "./workspaceStore";

export interface AutonomyAssetLibrary {
  schemaVersion: 2;
  aircraft: AutonomyAircraftProfile[];
  maps: AutonomyMapPack[];
  externalAssets: AutonomyExternalAssetReference[];
}

export interface AutonomyExternalAssetReference {
  schemaVersion: 1;
  id: string;
  kind: "map" | "world" | "vehicle";
  name: string;
  sourceApplication: string;
  sourceFormat: string;
  version: string;
  maturity: "visual_only" | "physics_ready" | "simulation_ready" | "flight_ready" | "qualified";
  contentSha256: string;
  qualificationId: string | null;
  importedAt: string;
}

const STORAGE_PREFIX = "dronedream:autonomy-assets:v1";
const MAX_AIRCRAFT = 50;
const MAX_MAPS = 50;
const MAX_EXTERNAL_ASSETS = 100;

function aircraftAssetKey(aircraft: AutonomyAircraftProfile): string {
  return aircraft.agentCoreAssetId?.trim() || aircraft.id;
}

function mapAssetKey(mapPack: AutonomyMapPack): string {
  return mapPack.agentCoreAssetId?.trim() || mapPack.id;
}

function externalAssetKey(asset: AutonomyExternalAssetReference): string {
  const kind = asset.kind === "vehicle" ? "vehicle" : "map";
  return `${kind}:${asset.id}`;
}

function uniqueByKey<T>(items: T[], keyFor: (item: T) => string, maximum: number): T[] {
  const keys = new Set<string>();
  return items.filter((item) => {
    const key = keyFor(item);
    if (keys.has(key)) return false;
    keys.add(key);
    return true;
  }).slice(0, maximum);
}

function normalizeLibrary(library: AutonomyAssetLibrary): AutonomyAssetLibrary {
  const aircraft = uniqueByKey(library.aircraft, aircraftAssetKey, MAX_AIRCRAFT);
  const maps = uniqueByKey(library.maps, mapAssetKey, MAX_MAPS);
  const representedAssetIds = new Set([
    ...aircraft.map(aircraftAssetKey),
    ...maps.map(mapAssetKey),
  ]);
  const externalAssets = uniqueByKey(
    library.externalAssets.filter((asset) => !representedAssetIds.has(asset.id)),
    externalAssetKey,
    MAX_EXTERNAL_ASSETS,
  );
  return { schemaVersion: 2, aircraft, maps, externalAssets };
}

function storageKey(ownerId: string, edition: BrandEditionId): string {
  return `${STORAGE_PREFIX}:${encodeURIComponent(ownerId || "local")}:${edition}`;
}

function replaceById<T extends { id: string }>(items: T[], item: T, maximum: number): T[] {
  return [item, ...items.filter((candidate) => candidate.id !== item.id)].slice(0, maximum);
}

function normalizeAircraft(value: unknown): AutonomyAircraftProfile | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<AutonomyAircraftProfile>;
  if (candidate.schemaVersion !== 2 || typeof candidate.id !== "string" || typeof candidate.name !== "string") return null;
  return normalizeAutonomyWorkspace({
    ...defaultAutonomyWorkspace(),
    aircraft: candidate,
  }).aircraft;
}

function normalizeMap(value: unknown): AutonomyMapPack | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<AutonomyMapPack>;
  if (candidate.schemaVersion !== 2 || typeof candidate.id !== "string" || typeof candidate.name !== "string") return null;
  return normalizeAutonomyWorkspace({
    ...defaultAutonomyWorkspace(),
    mapPack: candidate,
  }).mapPack;
}

function normalizeExternalAsset(value: unknown): AutonomyExternalAssetReference | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<AutonomyExternalAssetReference>;
  if (
    candidate.schemaVersion !== 1
    || typeof candidate.id !== "string"
    || !/^[a-z0-9][a-z0-9._-]{2,159}$/u.test(candidate.id)
    || !["map", "world", "vehicle"].includes(String(candidate.kind))
    || typeof candidate.name !== "string"
    || !candidate.name.trim()
    || typeof candidate.sourceApplication !== "string"
    || typeof candidate.sourceFormat !== "string"
    || typeof candidate.version !== "string"
    || !["visual_only", "physics_ready", "simulation_ready", "flight_ready", "qualified"].includes(String(candidate.maturity))
    || typeof candidate.contentSha256 !== "string"
    || !/^[0-9a-f]{64}$/u.test(candidate.contentSha256)
    || (candidate.qualificationId !== null
      && candidate.qualificationId !== undefined
      && (typeof candidate.qualificationId !== "string"
        || !/^asset-qualification-[0-9a-f]{24}$/u.test(candidate.qualificationId)))
    || typeof candidate.importedAt !== "string"
    || Number.isNaN(new Date(candidate.importedAt).getTime())
  ) return null;
  return {
    schemaVersion: 1,
    id: candidate.id,
    kind: candidate.kind as AutonomyExternalAssetReference["kind"],
    name: candidate.name.trim().slice(0, 160),
    sourceApplication: candidate.sourceApplication.trim().slice(0, 120),
    sourceFormat: candidate.sourceFormat.trim().slice(0, 80),
    version: candidate.version.trim().slice(0, 80),
    maturity: candidate.maturity as AutonomyExternalAssetReference["maturity"],
    contentSha256: candidate.contentSha256,
    qualificationId: typeof candidate.qualificationId === "string" ? candidate.qualificationId : null,
    importedAt: candidate.importedAt,
  };
}

export function withExternalAutonomyAsset(
  library: AutonomyAssetLibrary,
  asset: AutonomyExternalAssetReference,
): AutonomyAssetLibrary {
  const normalized = normalizeExternalAsset(asset);
  if (!normalized) return library;
  return normalizeLibrary({
    ...library,
    externalAssets: [
      normalized,
      ...library.externalAssets.filter((candidate) => (
        externalAssetKey(candidate) !== externalAssetKey(normalized)
      )),
    ].slice(0, MAX_EXTERNAL_ASSETS),
  });
}

export function withCurrentAutonomyAssets(
  library: AutonomyAssetLibrary,
  workspace: AutonomyWorkspaceState,
): AutonomyAssetLibrary {
  const publicAssets = defaultAutonomyWorkspace();
  return normalizeLibrary({
    schemaVersion: 2,
    aircraft: replaceById(
      replaceById(library.aircraft, publicAssets.aircraft, MAX_AIRCRAFT),
      workspace.aircraft,
      MAX_AIRCRAFT,
    ),
    maps: replaceById(
      replaceById(library.maps, publicAssets.mapPack, MAX_MAPS),
      workspace.mapPack,
      MAX_MAPS,
    ),
    externalAssets: library.externalAssets,
  });
}

export function loadAutonomyAssetLibrary(
  ownerId: string,
  edition: BrandEditionId,
  workspace: AutonomyWorkspaceState,
  storage: Pick<Storage, "getItem"> = window.localStorage,
): AutonomyAssetLibrary {
  try {
    const raw = JSON.parse(storage.getItem(storageKey(ownerId, edition)) ?? "null") as Partial<AutonomyAssetLibrary> | null;
    const aircraft = Array.isArray(raw?.aircraft)
      ? raw.aircraft.map(normalizeAircraft).filter((item): item is AutonomyAircraftProfile => Boolean(item))
      : [];
    const maps = Array.isArray(raw?.maps)
      ? raw.maps.map(normalizeMap).filter((item): item is AutonomyMapPack => Boolean(item))
      : [];
    const externalAssets = Array.isArray(raw?.externalAssets)
      ? raw.externalAssets.map(normalizeExternalAsset).filter((item): item is AutonomyExternalAssetReference => Boolean(item))
      : [];
    return withCurrentAutonomyAssets(normalizeLibrary({ schemaVersion: 2, aircraft, maps, externalAssets }), workspace);
  } catch {
    return withCurrentAutonomyAssets({ schemaVersion: 2, aircraft: [], maps: [], externalAssets: [] }, workspace);
  }
}

export function saveAutonomyAssetLibrary(
  ownerId: string,
  edition: BrandEditionId,
  library: AutonomyAssetLibrary,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): AutonomyAssetLibrary {
  const normalized = normalizeLibrary({
    schemaVersion: 2,
    aircraft: library.aircraft.map(normalizeAircraft).filter((item): item is AutonomyAircraftProfile => Boolean(item)).slice(0, MAX_AIRCRAFT),
    maps: library.maps.map(normalizeMap).filter((item): item is AutonomyMapPack => Boolean(item)).slice(0, MAX_MAPS),
    externalAssets: library.externalAssets
      .map(normalizeExternalAsset)
      .filter((item): item is AutonomyExternalAssetReference => Boolean(item))
      .slice(0, MAX_EXTERNAL_ASSETS),
  });
  storage.setItem(storageKey(ownerId, edition), JSON.stringify(normalized));
  return normalized;
}
