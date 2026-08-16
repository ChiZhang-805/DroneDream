import type { BrandEditionId } from "../../brand/edition-brand.generated";
import {
  defaultAutonomyWorkspace,
  normalizeAutonomyWorkspace,
  type AutonomyAircraftProfile,
  type AutonomyMapPack,
  type AutonomyWorkspaceState,
} from "./workspaceStore";

export interface AutonomyAssetLibrary {
  schemaVersion: 1;
  aircraft: AutonomyAircraftProfile[];
  maps: AutonomyMapPack[];
}

const STORAGE_PREFIX = "dronedream:autonomy-assets:v1";
const MAX_AIRCRAFT = 50;
const MAX_MAPS = 50;

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

export function withCurrentAutonomyAssets(
  library: AutonomyAssetLibrary,
  workspace: AutonomyWorkspaceState,
): AutonomyAssetLibrary {
  const publicAssets = defaultAutonomyWorkspace();
  return {
    schemaVersion: 1,
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
  };
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
    return withCurrentAutonomyAssets({ schemaVersion: 1, aircraft, maps }, workspace);
  } catch {
    return withCurrentAutonomyAssets({ schemaVersion: 1, aircraft: [], maps: [] }, workspace);
  }
}

export function saveAutonomyAssetLibrary(
  ownerId: string,
  edition: BrandEditionId,
  library: AutonomyAssetLibrary,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): AutonomyAssetLibrary {
  const normalized: AutonomyAssetLibrary = {
    schemaVersion: 1,
    aircraft: library.aircraft.map(normalizeAircraft).filter((item): item is AutonomyAircraftProfile => Boolean(item)).slice(0, MAX_AIRCRAFT),
    maps: library.maps.map(normalizeMap).filter((item): item is AutonomyMapPack => Boolean(item)).slice(0, MAX_MAPS),
  };
  storage.setItem(storageKey(ownerId, edition), JSON.stringify(normalized));
  return normalized;
}
